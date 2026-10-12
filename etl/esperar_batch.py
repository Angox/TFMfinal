import argparse
import os
import sys
import time

ESTADOS_TERMINALES = ("SUCCEEDED", "FAILED")

ESTADOS_EN_CURSO = ("SUBMITTED", "PENDING", "RUNNABLE", "STARTING", "RUNNING")


def resumir_job(job):
    job_id = job.get("jobId", "?")
    nombre = job.get("jobName", "?")
    estado = job.get("status", "UNKNOWN")
    motivo = job.get("statusReason") or ""

    propiedades = job.get("arrayProperties") or {}
    tamano = propiedades.get("size")

    if tamano:
        resumen = propiedades.get("statusSummary") or {}
        exitosos = int(resumen.get("SUCCEEDED", 0))
        fallidos = int(resumen.get("FAILED", 0))
        en_curso = max(int(tamano) - exitosos - fallidos, 0)
        return {
            "id": job_id, "nombre": nombre, "estado": estado, "motivo": motivo,
            "array": True, "total": int(tamano),
            "exitosos": exitosos, "fallidos": fallidos, "en_curso": en_curso,
            "terminado": en_curso == 0,
        }

    terminado = estado in ESTADOS_TERMINALES
    return {
        "id": job_id, "nombre": nombre, "estado": estado, "motivo": motivo,
        "array": False, "total": 1,
        "exitosos": 1 if estado == "SUCCEEDED" else 0,
        "fallidos": 1 if estado == "FAILED" else 0,
        "en_curso": 0 if terminado else 1,
        "terminado": terminado,
    }


def agregar(resumenes):
    total = sum(r["total"] for r in resumenes)
    exitosos = sum(r["exitosos"] for r in resumenes)
    fallidos = sum(r["fallidos"] for r in resumenes)
    return {
        "total": total,
        "exitosos": exitosos,
        "fallidos": fallidos,
        "en_curso": sum(r["en_curso"] for r in resumenes),
        "terminado": all(r["terminado"] for r in resumenes) if resumenes else True,
        "pct_fallos": (fallidos / total * 100.0) if total else 0.0,
    }


def veredicto(progreso, umbral_fallos_pct=25.0, agotado=False):
    if agotado or not progreso["terminado"]:
        return False, (
            f"Se agotó la espera con {progreso['en_curso']} de {progreso['total']} "
            f"tareas sin terminar."
        )

    if progreso["total"] == 0:
        return False, "No se encoló ninguna tarea: la muestra salió vacía."

    if progreso["exitosos"] == 0:
        return False, (
            f"Las {progreso['total']} tareas han fallado: fallo sistémico "
            f"(imagen, permisos de S3 o catálogo). Revisar los logs en CloudWatch."
        )

    if progreso["pct_fallos"] > umbral_fallos_pct:
        return False, (
            f"Han fallado {progreso['fallidos']} de {progreso['total']} tareas "
            f"({progreso['pct_fallos']:.1f} %), por encima del umbral del "
            f"{umbral_fallos_pct:.0f} %."
        )

    if progreso["fallidos"]:
        return True, (
            f"{progreso['exitosos']} de {progreso['total']} tareas correctas. "
            f"{progreso['fallidos']} han fallado, dentro del umbral "
            f"(registradas en `resultados_web/api/fallidos/`)."
        )

    return True, f"Las {progreso['total']} tareas han terminado correctamente."


def formatear_progreso(resumenes, progreso, segundos):
    lineas = [
        f"[{int(segundos // 60):>3d} min] "
        f"{progreso['exitosos']}/{progreso['total']} listos, "
        f"{progreso['fallidos']} fallidos, {progreso['en_curso']} en curso"
    ]
    for r in resumenes:
        detalle = (f"{r['exitosos']}{r['fallidos']}{r['en_curso']}⋯"
                   if r["array"] else r["estado"])
        lineas.append(f"    {r['nombre']:<26} {r['estado']:<10} {detalle}")
    return "\n".join(lineas)


def esperar(cliente, job_ids, timeout_minutos=240, intervalo=30,
            umbral_fallos_pct=25.0, salida=print, dormir=time.sleep):
    if not job_ids:
        return False, "No se recibió ningún identificador de trabajo.", agregar([])

    limite = timeout_minutos * 60
    inicio = 0.0
    ultimo_progreso = agregar([])

    while True:
        respuesta = cliente.describe_jobs(jobs=list(job_ids))
        resumenes = [resumir_job(j) for j in respuesta.get("jobs", [])]
        ultimo_progreso = agregar(resumenes)

        salida(formatear_progreso(resumenes, ultimo_progreso, inicio))

        if ultimo_progreso["terminado"]:
            for r in resumenes:
                if r["fallidos"] and r["motivo"]:
                    salida(f"     {r['nombre']}: {r['motivo']}")
            ok, motivo = veredicto(ultimo_progreso, umbral_fallos_pct)
            return ok, motivo, ultimo_progreso

        if inicio >= limite:
            ok, motivo = veredicto(ultimo_progreso, umbral_fallos_pct, agotado=True)
            return ok, motivo, ultimo_progreso

        dormir(intervalo)
        inicio += intervalo


def main():
    ap = argparse.ArgumentParser(
        description="Espera a que terminen los trabajos de AWS Batch del ETL")
    ap.add_argument("--jobs", nargs="+", required=True,
                    help="identificadores devueltos por `aws batch submit-job`")
    ap.add_argument("--timeout-minutos", type=int, default=240)
    ap.add_argument("--intervalo", type=int, default=30,
                    help="segundos entre sondeos")
    ap.add_argument("--umbral-fallos-pct", type=float, default=25.0,
                    help="porcentaje de tareas fallidas que aún se tolera")
    ap.add_argument("--resumen-github", default=os.getenv("GITHUB_STEP_SUMMARY"),
                    help="fichero donde escribir el resumen del run")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    import boto3
    cliente = boto3.client("batch", region_name=os.getenv("AWS_REGION"))

    print(f"⏳ Esperando a {len(args.jobs)} trabajos de Batch "
          f"(límite {args.timeout_minutos} min, sondeo cada {args.intervalo} s)",
          flush=True)

    ok, motivo, progreso = esperar(
        cliente, args.jobs,
        timeout_minutos=args.timeout_minutos,
        intervalo=args.intervalo,
        umbral_fallos_pct=args.umbral_fallos_pct,
        salida=lambda t: print(t, flush=True),
    )

    print(("" if ok else "") + motivo, flush=True)

    if args.resumen_github:
        try:
            with open(args.resumen_github, "a", encoding="utf-8") as f:
                f.write(f"### ETL en AWS Batch\n\n")
                f.write(f"{'' if ok else ''} {motivo}\n\n")
                f.write(f"| Tareas | Correctas | Fallidas | Sin terminar |\n")
                f.write(f"|---|---|---|---|\n")
                f.write(f"| {progreso['total']} | {progreso['exitosos']} | "
                        f"{progreso['fallidos']} | {progreso['en_curso']} |\n")
        except Exception as e:
            print(f"No se pudo escribir el resumen: {e}", flush=True)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
