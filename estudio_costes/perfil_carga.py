from dataclasses import dataclass, field

UNIDADES = {
    "computo_lote_vcpu_h": "vCPU·h",
    "computo_lote_gb_h": "GB·h",
    "computo_web_vcpu_h": "vCPU·h",
    "computo_web_gb_h": "GB·h",
    "almacenamiento_gb_mes": "GB·mes",
    "salida_internet_gb": "GB",
    "peticiones_escritura_millar": "millar",
    "peticiones_lectura_millar": "millar",
    "registro_contenedores_gb_mes": "GB·mes",
    "logs_gb": "GB",
    "llm_tokens_entrada_millon": "millón de tokens",
    "llm_tokens_salida_millon": "millón de tokens",
}

RECURSOS_POR_TALLA = {
    "S": {"vcpu": 1, "gb": 4},
    "M": {"vcpu": 2, "gb": 8},
    "L": {"vcpu": 4, "gb": 16},
}


@dataclass
class PerfilCarga:
    puertos_por_talla: dict = field(default_factory=lambda: {"S": 30, "M": 8, "L": 2})
    horas_por_puerto: dict = field(default_factory=lambda: {"S": 0.5, "M": 1.0, "L": 2.0})
    ejecuciones_etl_mes: int = 1
    fraccion_interrumpible: float = 1.0

    vcpu_web: float = 4.0
    gb_web: float = 8.0
    horas_activas_web_mes: float = 120.0
    peticiones_web_mes: int = 50_000

    almacenamiento_gb: float = 60.0
    salida_internet_gb_mes: float = 40.0
    escrituras_s3_mes: int = 60_000
    lecturas_s3_mes: int = 400_000

    consultas_copiloto_mes: int = 2_000
    tokens_entrada_por_consulta: int = 2_000
    tokens_salida_por_consulta: int = 250

    registro_contenedores_gb: float = 6.0
    logs_gb_mes: float = 2.0

    def horas_computo_lote(self):
        vcpu_h = 0.0
        gb_h = 0.0
        for talla, n in self.puertos_por_talla.items():
            recursos = RECURSOS_POR_TALLA[talla]
            horas = n * self.horas_por_puerto[talla] * self.ejecuciones_etl_mes
            vcpu_h += horas * recursos["vcpu"]
            gb_h += horas * recursos["gb"]
        return vcpu_h, gb_h

    def horas_contenedor(self):
        return sum(n * self.horas_por_puerto[talla] * self.ejecuciones_etl_mes
                   for talla, n in self.puertos_por_talla.items())

    def consumos(self):
        vcpu_lote, gb_lote = self.horas_computo_lote()
        return {
            "computo_lote_vcpu_h": vcpu_lote,
            "computo_lote_gb_h": gb_lote,
            "computo_web_vcpu_h": self.vcpu_web * self.horas_activas_web_mes,
            "computo_web_gb_h": self.gb_web * self.horas_activas_web_mes,
            "almacenamiento_gb_mes": self.almacenamiento_gb,
            "salida_internet_gb": self.salida_internet_gb_mes,
            "peticiones_escritura_millar": self.escrituras_s3_mes / 1000.0,
            "peticiones_lectura_millar": self.lecturas_s3_mes / 1000.0,
            "registro_contenedores_gb_mes": self.registro_contenedores_gb,
            "logs_gb": self.logs_gb_mes,
            "llm_tokens_entrada_millon": (self.consultas_copiloto_mes
                                          * self.tokens_entrada_por_consulta / 1e6),
            "llm_tokens_salida_millon": (self.consultas_copiloto_mes
                                         * self.tokens_salida_por_consulta / 1e6),
        }

    def total_puertos(self):
        return sum(self.puertos_por_talla.values())

    def describir(self):
        vcpu_lote, gb_lote = self.horas_computo_lote()
        return {
            "puertos_procesados_mes": self.total_puertos() * self.ejecuciones_etl_mes,
            "puertos_por_talla": dict(self.puertos_por_talla),
            "horas_contenedor_etl": round(self.horas_contenedor(), 2),
            "vcpu_hora_lote": round(vcpu_lote, 2),
            "gb_hora_lote": round(gb_lote, 2),
            "fraccion_interrumpible": self.fraccion_interrumpible,
        }
