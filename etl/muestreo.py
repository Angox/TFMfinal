def reparto_proporcional(tamanos, n_total):
    estratos = {k: v for k, v in tamanos.items() if v > 0}
    asignado = {k: 0 for k in tamanos}
    if not estratos:
        return asignado

    total = sum(estratos.values())
    n_total = min(n_total, total)

    if n_total < len(estratos):
        for k in sorted(estratos, key=lambda k: -estratos[k])[:n_total]:
            asignado[k] = 1
        return asignado

    restante = n_total - len(estratos)
    cuotas = {k: restante * estratos[k] / total for k in estratos}
    enteros = {k: int(cuotas[k]) for k in estratos}
    sobrante = restante - sum(enteros.values())
    for k in sorted(estratos, key=lambda k: cuotas[k] - enteros[k], reverse=True)[:sobrante]:
        enteros[k] += 1

    for k in estratos:
        asignado[k] = min(1 + enteros[k], estratos[k])
    return asignado


def muestra_repartida_por_paises(puertos, n, rng):
    if n >= len(puertos):
        return list(puertos)

    por_pais = {}
    for p in puertos:
        por_pais.setdefault(str(p.get("country", "desconocido")), []).append(p)
    for lista in por_pais.values():
        rng.shuffle(lista)

    paises = sorted(por_pais)
    rng.shuffle(paises)

    seleccion, vuelta = [], 0
    while len(seleccion) < n:
        avanzo = False
        for pais in paises:
            if vuelta < len(por_pais[pais]):
                seleccion.append(por_pais[pais][vuelta])
                avanzo = True
                if len(seleccion) == n:
                    break
        if not avanzo:
            break
        vuelta += 1
    return seleccion


def anadir_puertos_fijos(seleccionados, catalogo, portids):
    if not portids:
        return list(seleccionados), set()

    buscados = set(portids)
    ya_dentro = {str(p.get("portid") or "") for p in seleccionados}
    seleccion, anadidos = list(seleccionados), set()
    for puerto in catalogo:
        portid = str(puerto.get("portid") or "")
        if portid in buscados and portid not in ya_dentro:
            seleccion.append(puerto)
            ya_dentro.add(portid)
            anadidos.add(portid)
    return seleccion, anadidos
