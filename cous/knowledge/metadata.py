"""Extração de metadados estruturados por tipo de documento.

Classifica o documento por palavras-chave e extrai campos comuns
(manufacturer, part_number, supply_voltage, interface, etc.) + campos
específicos do tipo no campo `extra` (JSONB).

Tipos suportados:
  datasheet_motor      — motores DC (Faulhaber, Maxon, Portescap)
  datasheet_sensor     — sensores (INA219, MLX90393, MPU-6000, ATS177)
  datasheet_interface  — conversores, expansores IO (CH343, CH422)
  datasheet_passive    — resistores, capacitores (WSLT2512)
  measurement          — medições do Cous
  service_order        — ordens de serviço (OS System)
  academic             — TCC, dissertação, tese, monografia (nacional)
  book                 — livros de engenharia (editora, ISBN, ficha catalográfica)
  machine_manual       — manuais de máquinas de tatuagem (pen, rotativa, bobina)
  power_supply         — fontes de alimentação, baterias externas (Musotoku, InkMachines)
  battery              — baterias de máquinas de tatuagem (PowerBolt, Lightning)
  cartridge            — cartuchos/agulhas descartáveis (Krieg, Bishop, Electric Ink)
  generic              — qualquer outro documento
"""

from __future__ import annotations

import re
from typing import Any

# ── Tabela de classificação ─────────────────────────────────────────────

# Palavras-chave → (document_type, category)
_KEYWORD_CLASSIFIER: list[tuple[list[str], str, str]] = [
    # Motores
    (["nominal voltage", "stall torque", "no-load speed", "back-emf constant",
      "torque constant", "rotor inductance", "speed constant"], "datasheet_motor", "motor"),
    # Sensores de corrente/potência
    (["current shunt", "power monitor", "bus voltage", "shunt voltage",
      "current register", "power register", "zero-drift", "bidirectional"],
     "datasheet_sensor", "current_power"),
    # Sensores magnéticos
    (["triaxis", "magnetic node", "hall technology", "magnetic flux density",
      "magnetic field sensor", "hall sensor"], "datasheet_sensor", "magnetic"),
    # IMU / acelerômetro / giroscópio
    (["gyroscope", "accelerometer", "motion processing", "motion tracking",
      "angular rate", "digital motion processor", "invensense"],
     "datasheet_sensor", "imu"),
    # Conversores USB/UART
    (["usb to uart", "usb serial", "baud rate", "uart interface",
      "flow control", "rs-232"], "datasheet_interface", "converter"),
    # Expansores IO
    (["gpio expander", "io expander", "i2c gpio", "parallel io"],
     "datasheet_interface", "io_expander"),
    # Componentes passivos
    (["power metal strip", "shunt resistor", "current sense resistor",
      "surface mount resistor", "wirewound resistor"],
     "datasheet_passive", "resistor"),
    # Ordens de serviço
    (["cliente:", "cnpj / cpf:", "cel:", "endereço:",
      "ordem de serviço", "os system"], "service_order", "os"),
    # Medições
    (["## cabecalho - fabricante:", "## resumo tecnico"],
     "measurement", "measurement"),
    # Documentos acadêmicos (PT-BR) — antes de book e machine_manual
    (["trabalho de conclusão de curso", "dissertação", "tese",
      "monografia", "orientador", "universidade", "faculdade",
      "programa de pós-graduação", "departamento acadêmico"],
     "academic", "academic"),
    # Livros de engenharia (ISBN, editora, ficha catalográfica)
    (["copyright ©", "isbn", "ficha catalográfica",
      "editora", "edição", "impresso no brasil",
      "tradução autorizada", "todos os direitos reservados"],
     "book", "engineering_book"),
    # Baterias de máquinas (PT/EN) — antes de power_supply e machine_manual
    (["machine battery", "usb-c battery", "li-ion", "lipo",
      "battery capacity", "mah", "rechargeable battery",
      "powerbolt", "lightning battery", "bateria", "acumulador",
      "battery cell", "removable battery"],
     "battery", "battery"),
    # Fontes de alimentação / baterias externas (PT/EN) — antes de machine_manual
    (["power supply", "fonte de alimentação", "footswitch",
      "voltage output", "power input", "powerpack",
      "overcurrent", "memory preset", "nitro",
      "battery pack", "charger bay", "power cord",
      "output current", "short circuit"],
     "power_supply", "power_supply"),
    # Cartuchos / agulhas descartáveis (PT/EN) — antes de machine_manual
    (["cartucho", "cartridge", "agulha descartável", "descartável",
      "blister", "uso único", "single use", "óxido de etileno",
      "biqueira", "needle cartridge", "estéril", "produto estéril",
      "embalagem individual", "esterilizado por", "descartáveis",
      "round liner", "round shader", "curved magnum", "bugpin",
      "agulhas descartáveis", "configurações de agulha"],
     "cartridge", "cartridge"),
    # Manuais de máquinas de tatuagem (PT/EN)
    (["saliência da agulha", "frequência de perfuração",
      "máquina de tatuagem", "tattoo machine", "needle cartridge",
      "instruções de uso", "instruções de segurança",
      "modo de usar", "esterilização", "autoclave",
      "tatuagem", "tattoo",
      "needle depth", "stroke length", "give adjustment",
      "operating voltage", "wireless tattoo", "power bolt",
      "tattooing machine", "cartridge needles", "safety membrane",
      "máquina", "caneta", "agulha", "cartucho", "needle", "cartridge"],
     "machine_manual", "tattoo_machine"),
]

# Fabricantes conhecidos
_KNOWN_MANUFACTURERS: dict[str, str] = {
    # Componentes eletrônicos
    "faulhaber": "Faulhaber",
    "maxon": "Maxon",
    "portescap": "Portescap",
    "texas instruments": "Texas Instruments",
    "melexis": "Melexis",
    "invensense": "InvenSense",
    "vishay": "Vishay",
    "wch": "WCH",
    "diodes": "Diodes Inc.",
    "allegro": "Allegro MicroSystems",
    "stmicroelectronics": "STMicroelectronics",
    "st microelectronics": "STMicroelectronics",
    # Cartuchos / acessórios
    "krieg tattoo": "Krieg Tattoo",
    "harpia": "Harpia",
    "onskin": "ONSKIN",
    "white head": "White Head",
    "iron works": "Iron Works",
}


# Editoras conhecidas (livros de engenharia)
_KNOWN_PUBLISHERS: dict[str, str] = {
    "mcgraw-hill": "McGraw-Hill",
    "mcgraw hill": "McGraw-Hill",
    "pearson": "Pearson",
    "prentice hall": "Prentice Hall",
    "bookman": "Bookman",
    "artmed": "Artmed",
    "ltc": "LTC",
    "blucher": "Blucher",
    "cengage": "Cengage Learning",
    "saraiva": "Saraiva",
    "alta books": "Alta Books",
    "novatec": "Novatec",
    "ciência moderna": "Ciência Moderna",
}


def extract_metadata(text: str, source_path: str = "") -> dict[str, Any]:
    """Detecta o tipo de documento e extrai metadados estruturados."""
    text_lower = text.lower()

    # Classifica por palavras-chave
    doc_type, category = _classify(text_lower)

    # Campos base (todos os tipos)
    manufacturer = _detect_manufacturer(text_lower)
    if not manufacturer:
        manufacturer = _detect_manufacturer(source_path.lower())

    metadata: dict[str, Any] = {
        "document_type": doc_type,
        "category": category,
        "title": _extract_title(text, source_path),
        "manufacturer": manufacturer,
        "model": _extract_part_number(text, text_lower, doc_type),
        "extra": {},
    }

    # Extrai campos específicos por categoria
    extra = metadata["extra"]

    # ── Campos comuns a todos os datasheets ──
    if doc_type.startswith("datasheet_"):
        _extract_common_datasheet_fields(text, text_lower, extra)

    # ── Campos específicos por categoria ──
    if category == "motor":
        _extract_motor_fields(text, text_lower, extra)
    elif category in ("current_power", "magnetic", "imu"):
        _extract_sensor_fields(text, text_lower, category, extra)
    elif category in ("converter", "io_expander"):
        _extract_interface_fields(text, text_lower, extra)
    elif category == "resistor":
        _extract_passive_fields(text, text_lower, extra)
    elif doc_type == "measurement":
        _extract_measurement_fields(text, extra)
        metadata["manufacturer"] = str(extra.pop("fabricante", ""))
        metadata["model"] = str(extra.pop("modelo", ""))
    elif doc_type == "service_order":
        _extract_service_order_fields(text, extra)
    elif doc_type == "book":
        _extract_book_fields(text, text_lower, extra)
        metadata["manufacturer"] = str(extra.pop("publisher", ""))
        book_title = extra.pop("book_title", None)
        if book_title:
            metadata["title"] = str(book_title)
    elif doc_type == "academic":
        _extract_academic_fields(text, text_lower, extra)
        metadata["manufacturer"] = str(extra.pop("institution", ""))
        metadata["model"] = str(extra.pop("author", ""))
        academic_title = extra.pop("academic_title", None)
        if academic_title:
            metadata["title"] = str(academic_title)
    elif doc_type == "machine_manual":
        _extract_machine_manual_fields(text, text_lower, extra)
        if not metadata["model"]:
            metadata["model"] = str(extra.pop("equipment_model", ""))
    elif doc_type == "power_supply":
        _extract_power_supply_fields(text, text_lower, extra)
        if not metadata["model"]:
            metadata["model"] = str(extra.pop("equipment_model", ""))
    elif doc_type == "battery":
        _extract_battery_fields(text, text_lower, extra)
        if not metadata["model"]:
            metadata["model"] = str(extra.pop("equipment_model", ""))
    elif doc_type == "cartridge":
        _extract_cartridge_fields(text, text_lower, extra)
        if not metadata["model"]:
            metadata["model"] = str(extra.pop("equipment_model", ""))

    # Limpa valores vazios
    metadata["extra"] = {k: v for k, v in extra.items() if v not in (None, "", [])}

    return metadata


# ── Classificação ────────────────────────────────────────────────────────


def _classify(text_lower: str) -> tuple[str, str]:
    """Classifica o documento por scoring normalizado: percentual de keywords batidas.
    Threshold mínimo = 2 matches absolutos. Em empate, maior cobertura vence."""
    best_type, best_category = "generic", "general"
    best_score = 0.0
    best_matches = 0
    for keywords, doc_type, category in _KEYWORD_CLASSIFIER:
        matches = sum(1 for kw in keywords if kw in text_lower)
        if matches < 2:
            continue
        score = matches / len(keywords)  # percentual de cobertura
        if score > best_score or (score == best_score and matches > best_matches):
            best_score = score
            best_matches = matches
            best_type, best_category = doc_type, category
    return best_type, best_category


# ── Extração comum a todos os datasheets ────────────────────────────────


def _extract_common_datasheet_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos presentes na maioria dos datasheets. Valores numéricos puros."""
    # Tensão de alimentação (NUMBER)
    for pattern in [
        r"supply voltage[:\s]+([\d.,]+)",
        r"operating voltage[:\s]+([\d.,]+)",
        r"vdd\s*(?:=|:)\s*([\d.,]+)",
        r"input voltage[:\s]+([\d.,]+)",
    ]:
        val = _extract_number(pattern, text)
        if val is not None:
            extra["supply_voltage"] = val
            break

    # Consumo de corrente (NUMBER)
    for pattern in [
        r"supply current[:\s]+([\d.,]+)",
        r"operating current[:\s]+([\d.,]+)",
        r"current consumption[:\s]+([\d.,]+)",
    ]:
        val = _extract_number(pattern, text)
        if val is not None:
            extra["current_consumption"] = val
            break

    # Interface de comunicação
    if "i2c" in text_lower or "i²c" in text_lower:
        extra["interface"] = "I2C"
    if "spi" in text_lower:
        extra["interface"] = f"{extra.get('interface', '')} + SPI".strip(" +")
    if "smbus" in text_lower:
        extra["interface"] = f"{extra.get('interface', '')} + SMBus".strip(" +")
    if "uart" in text_lower:
        extra["interface"] = f"{extra.get('interface', '')} + UART".strip(" +")

    # Encapsulamento
    pkg = _extract_package(text_lower)
    if pkg:
        extra["package"] = pkg

    # Temperatura de operação (min / max)
    for pattern in [
        r"operating temperature[:\s]+([-+\d.,\s–—]+)°",
        r"operating temperature range[:\s]+[–\-]?\s*([-+\d.,\s–—]+)°",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1).strip()
            # Split por "to", "–", "—", ou espaço+hífen (mas não hífen de número negativo)
            parts = re.split(r"\s+(?:to|–|—)\s+|\s+-\s+", raw)
            nums = []
            for p in parts:
                p = p.strip().replace(",", ".")
                try:
                    nums.append(float(p))
                except ValueError:
                    pass
            if len(nums) >= 2:
                extra["operating_temp_min"] = nums[0]
                extra["operating_temp_max"] = nums[1]
            break


# ── Extração específica: motores ────────────────────────────────────────


def _extract_motor_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos específicos de datasheets de motor DC. Valores numéricos puros."""
    # Campos numéricos (15 métricas)
    num_fields = {
        "nominal_voltage": r"nominal voltage[:\s]+([\d.,]+)",
        "no_load_speed": r"no-load speed[:\s]+([\d\s,.]+)",
        "stall_torque": r"stall torque[:\s]+([\d,.]+)",
        "torque_constant": r"torque constant[:\s]+([\d,.]+)",
        "max_speed": r"speed up to[:\s]+([\d\s,.]+)",
        "efficiency_max": r"efficiency[,\s]*max[.\s:]+(\d+)",
        "mass": r"mass[:\s]+([\d,.]+)",
        "shaft_diameter": r"shaft diameter[:\s]+([\d,.]+)",
    }
    for key, pattern in num_fields.items():
        val = _extract_number(pattern, text)
        if val is not None:
            extra[key] = val

    # Campo texto
    extra["magnet_material"] = _extract_value(r"magnet material[:\s]+(\w+)", text)


# ── Extração específica: sensores ───────────────────────────────────────


def _extract_sensor_fields(text: str, text_lower: str, category: str, extra: dict) -> None:
    """Campos específicos de sensores. Valores numéricos puros."""
    # Resolução / bits (NUMBER)
    bits = re.search(r"(\d{2})\s*-bit", text_lower)
    if bits:
        extra["resolution"] = float(bits.group(1))

    # Eixos (NUMBER)
    if "3-axis" in text_lower or "triaxis" in text_lower:
        extra["axes"] = 3.0
    elif "6-axis" in text_lower:
        extra["axes"] = 6.0

    # Range de medição
    if category == "magnetic":
        # magnetic_range_min / magnetic_range_max
        match = re.search(
            r"magnetic\s*(?:flux\s*density|field)\s*(?:range)?[:\s]+([\d.,]+\s*(?:to\s+)?[\d.,]*)",
            text, re.IGNORECASE
        )
        if match:
            raw = match.group(1).strip()
            parts = re.split(r"\s*(?:to|–|—|-)\s*", raw)
            nums = []
            for p in parts:
                try:
                    nums.append(float(p.replace(",", ".").strip()))
                except ValueError:
                    pass
            if len(nums) >= 2:
                extra["magnetic_range_min"] = nums[0]
                extra["magnetic_range_max"] = nums[1]
    elif category == "imu":
        val = _extract_number(r"gyroscope range[:\s]+([\d.,]+)", text)
        if val is None:
            val = _extract_number(r"full-scale range[:\s]+([\d.,]+)", text)
        if val is not None:
            extra["gyro_range"] = val
        val = _extract_number(r"accelerometer range[:\s]+([\d.,]+)", text)
        if val is not None:
            extra["accel_range"] = val

    # Sensor de temperatura onboard (BOOLEAN)
    if "temperature sensor" in text_lower:
        extra["temp_sensor"] = True


# ── Extração específica: interfaces ─────────────────────────────────────


def _extract_interface_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos específicos de conversores/expansores IO. Valores numéricos puros."""
    val = _extract_number(r"baud\s*(?:rate)?[:\s]+([\d.,]+)", text)
    if val is not None:
        extra["baud_rate"] = val
    val = _extract_number(r"gpio\s*(?:pins|channels)?[:\s]+(\d+)", text)
    if val is not None:
        extra["gpio_count"] = val


# ── Extração específica: passivos ───────────────────────────────────────


def _extract_passive_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos específicos de resistores/capacitores. Valores numéricos puros."""
    val = _extract_number(r"resistance[:\s]+([\d.,]+)", text)
    if val is not None:
        extra["resistance"] = val
    val = _extract_number(r"power rating[:\s]+([\d.,]+)", text)
    if val is not None:
        extra["power_rating"] = val
    val = _extract_number(r"tolerance[:\s]+([\d.,]+)", text)
    if val is not None:
        extra["tolerance"] = val


# ── Extração específica: medições e OS ──────────────────────────────────


def _extract_measurement_fields(text: str, extra: dict) -> None:
    """Campos de medição (fallback)."""
    extra["fabricante"] = _extract_value(r"fabricante[:\s]+([\w\s]+)", text)
    extra["modelo"] = _extract_value(r"modelo[:\s]+([\w\s]+)", text)
    extra["numero_serie"] = _extract_value(r"(?:s[ée]rie|serial)[:\s]+([\w\d-]+)", text)
    extra["tipo_coleta"] = _extract_value(r"tipo de coleta[:\s]+([\w-]+)", text)


def _extract_service_order_fields(text: str, extra: dict) -> None:
    """Campos de ordem de serviço. Layout de formulário com valores em colunas."""
    # Marca/modelo em layout de colunas: label na linha N, valor na linha N+1
    # Linha típica: "EQUIPAMENTO:    MARCA:    MODELO:"
    # Linha seguinte:"Pen            DKLAB     W1"
    extra["equipment_brand"] = _extract_value(r"marca:[^\n]*\n\s*\S+\s+(\S+)", text)
    if not extra["equipment_brand"]:
        extra["equipment_brand"] = _extract_value(r"marca[:\s]+(\S+)", text)
    # Modelo
    extra["equipment_model"] = _extract_value(r"modelo:[^\n]*\n\s*(?:\S+\s+){2}(\S+)", text)
    if not extra["equipment_model"]:
        extra["equipment_model"] = _extract_value(r"modelo[:\s]+(\S+)", text)
    # Número de série
    extra["equipment_serial"] = _extract_value(
        r"(?:n[º°]\s*(?:de|do)?\s*(?:s[ée]rie|serial)|s[ée]rie)[:\s]+([\w\d-]+)", text
    )
    # Data
    extra["service_date"] = _extract_value(r"data\s*(?:de|da)?\s*(?:entrada)?[:\s]+(\d{2}/\d{2}/\d{4})", text)
    # Técnico: nome na linha após "TÉCNICO RESPONSÁVEL:"
    extra["technician"] = _extract_value(
        r"t[ée]cnico\s*respons[áa]vel:[^\n]*\n\s*(\S+(?:\s+\S+){1,3})", text
    )
    if not extra["technician"]:
        extra["technician"] = _extract_value(r"t[ée]cnico[:\s]+(\S+(?:\s+\S+){1,3})", text)
    # Problema relatado (DEFEITO RELATADO)
    extra["symptoms"] = _extract_section(
        text, r"(?:defeito\s*relatado|problema\s*relatado|sintoma|reclamacao)[:\s]*"
    )
    # Observações técnicas (diagnóstico / análise)
    extra["diagnosis"] = _extract_section(
        text, r"(?:observa[çc][õo]es\s*t[ée]cnicas|diagn[óo]stico|laudo\s*t[ée]cnico)[:\s]*"
    )
    # Causa provável
    extra["defect_cause"] = _extract_section(
        text, r"(?:causa\s*prov[áa]vel|an[áa]lise\s*(?:de|do)\s*defeito|origem\s*do\s*problema)[:\s]*"
    )
    # Solução: PROPOSTA DE MANUTENÇÃO (formato limpo) ou DESCRIÇÃO DE SERVIÇOS
    res = _extract_section(
        text, r"proposta\s*de\s*manuten[çc][ãaâôõ]o[:\s]*"
    )
    if not res:
        res = _extract_section(
            text, r"(?:descri[çc][ãa]o\s*de\s*servi[çc]os|soluc[ãa]o|procedimento)[:\s]*"
        )
    if res:
        extra["resolution"] = _strip_table_header(res)
    # Peças: capturar linha após "DESCRIÇÃO DE PEÇAS"
    parts_match = re.search(
        r"descri[çc][ãa]o\s*de\s*pe[çc]as[^\n]*\n\s*(.+?)(?:\n\n|\n\s*(?:[A-ZÀ-Ú]{4,}|QTD\.)|\Z)",
        text, re.IGNORECASE | re.DOTALL
    )
    if parts_match:
        parts_text = parts_match.group(1).strip().replace("\n", " ")[:500]
        extra["parts_replaced"] = parts_text


# ── Extração específica: documentos acadêmicos ──────────────────────


def _extract_academic_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos de trabalhos acadêmicos (TCC, dissertação, tese, artigo)."""
    # Autor
    extra["author"] = _extract_academic_author(text)
    # Instituição
    extra["institution"] = _extract_academic_institution(text)
    # Ano
    extra["year"] = _extract_number(r"((?:19|20)\d{2})", text)
    # Tipo (TCC, Dissertação, Tese)
    if "dissertação" in text_lower or "dissertacao" in text_lower:
        extra["academic_type"] = "dissertação"
    elif "tese" in text_lower:
        extra["academic_type"] = "tese"
    elif "trabalho de conclusão" in text_lower or "tcc" in text_lower:
        extra["academic_type"] = "TCC"
    elif "monografia" in text_lower:
        extra["academic_type"] = "monografia"
    # Orientador
    extra["advisor"] = _extract_value(r"orientador[:\s]+(?:prof\.?\s*(?:dr\.?|dra\.?|me\.?|msc\.?)\s*)?([\w\s]+)", text)
    # Curso / Programa
    extra["course"] = _extract_value(r"curso de[:\s]+(\w[\w\s]+)", text)
    if not extra.get("course"):
        extra["course"] = _extract_value(r"programa de p[óo]s-gradua[çc][ãa]o em[:\s]+(\w[\w\s]+)", text)
    # Título do trabalho (primeira linha longa em caixa alta)
    extra["academic_title"] = _extract_academic_title(text)
    # Palavras-chave
    keywords = _extract_academic_keywords(text)
    if keywords:
        extra["keywords"] = keywords
    # Resumo (primeiras 300 caracteres após "RESUMO" ou "ABSTRACT")
    abstract = _extract_academic_abstract(text)
    if abstract:
        extra["abstract"] = abstract[:300]


def _extract_academic_title(text: str) -> str | None:
    """Extrai o título do trabalho acadêmico — linhas em caixa alta consecutivas."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line = line.strip()
        if len(line) >= 20 and line.isupper() and not any(
            kw in line.lower() for kw in ["universidade", "faculdade", "resumo",
                                           "abstract", "sumário", "referências",
                                           "palavras-chave", "keywords", "orientador",
                                           "isbn", "copyright"]
        ):
            # Junta com a próxima linha se também for caixa alta curta
            title = line
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.isupper() and len(next_line) >= 5:
                    title += " " + next_line
            return title.title()[:200]
    return None


def _extract_academic_author(text: str) -> str | None:
    """Extrai nome do autor (padrão brasileiro: SOBRENOME, Nome)."""
    # Padrão 1: "BORGES, Willian de Oliveira; Graduando; Unesc"
    for pattern in [
        r"\n[ \t]*([A-ZÀ-Ú][A-Za-zÀ-ü ,]{10,70});",     # SOBRENOME, Nome; (sem \n, termina em ;)
        r"\n([A-ZÀ-Ú][A-ZÀ-Ú\s]{10,60})\n",            # nome simples em caixa alta
        r"^([A-ZÀ-Ú][A-ZÀ-Ú\s]{10,60})$",               # início de linha
    ]:
        match = re.search(pattern, text, re.MULTILINE)
        if match:
            name = match.group(1).strip().rstrip(",").rstrip(";")
            if len(name.split()) >= 2:
                if not any(kw in name.lower() for kw in ["universidade", "faculdade", "centro", "departamento",
                                                            "programa", "engenharia", "tecnologia", "resumo",
                                                            "abstract", "sumário", "sumario", "referências",
                                                            "referencias", "referências bibliográficas"]):
                    return name.title()
    return None


def _extract_academic_institution(text: str) -> str | None:
    """Detecta instituição por nome conhecido."""
    text_lower = text.lower()
    institutions = {
        "utfpr": "UTFPR",
        "universidade tecnológica federal do paraná": "UTFPR",
        "ufsm": "UFSM",
        "universidade federal de santa maria": "UFSM",
        "usp": "USP",
        "universidade de são paulo": "USP",
        "unicamp": "UNICAMP",
        "universidade estadual de campinas": "UNICAMP",
        "ufsc": "UFSC",
        "universidade federal de santa catarina": "UFSC",
        "ufmg": "UFMG",
        "universidade federal de minas gerais": "UFMG",
        "ufrj": "UFRJ",
        "universidade federal do rio de janeiro": "UFRJ",
        "doctum": "Faculdade Doctum",
        "faculdade doctum": "Faculdade Doctum",
        "unesc": "UNESC",
        "universidade do extremo sul catarinense": "UNESC",
    }
    # Ordena por tamanho decrescente (nomes mais específicos primeiro)
    sorted_inst = sorted(institutions.items(), key=lambda x: -len(x[0]))
    for keyword, name in sorted_inst:
        if keyword in text_lower:
            return name
    return None


def _extract_academic_keywords(text: str) -> str | None:
    """Extrai palavras-chave (após 'Palavras-chave:' ou 'Keywords:')."""
    for pattern in [
        r"palavras-chave[:\s]+(.+?)(?:\n\n|\n(?:abstract|resumo|sumário|sumario))",
        r"keywords[:\s]+(.+?)(?:\n\n|\n(?:abstract|resumo))",
    ]:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            keywords = match.group(1).strip().replace("\n", " ")[:200]
            return keywords
    return None


def _extract_academic_abstract(text: str) -> str | None:
    """Extrai o resumo/abstract (texto após 'RESUMO' ou 'ABSTRACT')."""
    for pattern in [
        r"\nRESUMO\s*\n(.+?)(?:\n\n|\nABSTRACT|\nPalavras-chave)",
        r"\nABSTRACT\s*\n(.+?)(?:\n\n|\nRESUMO|\nKeywords)",
    ]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            abstract = match.group(1).strip().replace("\n", " ")[:300]
            return abstract
    return None


# ── Extração específica: livros de engenharia ─────────────────────────


def _extract_book_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos de livros técnicos/de engenharia."""
    # Título (mesmo extrator de títulos acadêmicos)
    extra["book_title"] = _extract_academic_title(text)
    # ISBN-10 ou ISBN-13 (formato flexível: com ou sem hífens)
    isbn = _extract_value(
        r"isbn[:\s]+([\d]{1,5}[-\s]?[\d]{1,7}[-\s]?[\d]{1,7}[-\s]?[\dX]+)",
        text
    )
    if not isbn:
        isbn = _extract_value(
            r"\b(97[89][-\s]?\d{1,5}[-\s]?\d{1,7}[-\s]?\d{1,7}[-\s]?\d)\b",
            text
        )
    if isbn:
        extra["isbn"] = isbn

    # Editora
    extra["publisher"] = _extract_book_publisher(text, text_lower)

    # Edição (NUMBER)
    edition = _extract_number(r"(\d{1,2})\s*[ªa]\.?\s*edi[çc][ãa]o", text)
    if edition is None:
        edition = _extract_number(r"(\d{1,2})(?:st|nd|rd|th)\s*edition", text)
    if edition is None:
        edition = _extract_number(r"(\d{1,2})\s*\.\s*ed\.", text)
    if edition is not None:
        extra["edition"] = edition

    # Ano (NUMBER)
    year = _extract_number(r"copyright[:\s©]*\s*(\d{4})", text)
    if year is None:
        year = _extract_number(r"©\s*(\d{4})", text)
    if year is not None:
        extra["year"] = year

    # Assunto / tópico principal
    extra["subject"] = _extract_book_subject(text, text_lower)

    # Número de páginas (NUMBER)
    pages = _extract_number(r"(\d{3,4})\s*p[áa]g(?:inas)?", text)
    if pages is not None:
        extra["pages"] = pages


def _extract_book_publisher(text: str, text_lower: str) -> str | None:
    """Detecta editora por nome conhecido ou extrai de 'Editora: ...'."""
    for keyword, name in _KNOWN_PUBLISHERS.items():
        if keyword in text_lower:
            return name
    return _extract_value(r"editora[:\s]+([\w\s]+?)(?:\n|$)", text)


def _extract_book_subject(text: str, text_lower: str) -> str | None:
    """Infere o assunto principal do livro por palavras-chave no título/conteúdo."""
    return _extract_value(
        r"((?:Eletr[ôo]nica|Circuitos|Sistemas\s+Digitais|Dispositivos\s+Eletr[ôo]nicos|Microeletr[ôo]nica|M[áa]quinas\s+El[ée]tricas|Eletromagnetismo|Controle|Processamento\s+de\s+Sinais|Eletr[ôo]nica\s+de\s+Pot[êe]ncia|Instrumenta[çc][ãa]o|Teoria\s+de\s+Circuitos)[\w\s]{0,40})",
        text
    )


# ── Extração específica: manuais de máquinas de tatuagem ──────────────


def _extract_machine_manual_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos de manuais de máquinas de tatuagem. Valores numéricos puros."""
    # Modelo — busca nome de modelo conhecido no texto
    extra["equipment_model"] = _extract_machine_model(text)
    # Tensão de operação (min / max)
    for pattern in [
        r'(\d+\.?\d*)\s*[–\-~àa]+\s*(\d+\.?\d*)\s*V(?:DC|olt)?',
        r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*V',
        r'(\d+)\s*à\s*(\d+)\s*V',
        r'Min\s*(\d+\.?\d*)\s*volts?\s*/\s*Max\s*(\d+\.?\d*)\s*volts?',
    ]:
        m = re.search(pattern, text, re.I)
        if m:
            extra["voltage_min_v"] = float(m.group(1))
            extra["voltage_max_v"] = float(m.group(2))
            break
    # RPM máximo
    rpm_matches = re.findall(r'(\d+[\d.]*)\s*(?:RPM|rpm)', text)
    if rpm_matches:
        extra["rpm_max"] = max(int(m.replace(".", "")) for m in rpm_matches)
    # Curso (mm)
    strokes = []
    for m in re.finditer(r'(\d+\.?\d*)\s*mm', text):
        v = float(m.group(1))
        if 1.5 <= v <= 5.0:
            strokes.append(v)
    if strokes:
        extra["stroke_options_mm"] = sorted(set(strokes))
    # Capacidade da bateria
    m = re.search(r'(\d+)\s*m[Aa]h', text)
    if m:
        extra["battery_capacity_mah"] = int(m.group(1))
    # Peso
    for pat in [r'(\d+)\s*g\b', r'Approx\.\s*(\d+)\s*g', r'Peso.*?(\d+)\s*g']:
        m = re.search(pat, text, re.I)
        if m:
            w = int(m.group(1))
            if 50 <= w <= 500:
                extra["weight_g"] = w
                break
    # Tipo de motor
    if 'brushless' in text_lower:
        extra["motor_type"] = "brushless"
    elif 'brush dc' in text_lower:
        extra["motor_type"] = "brush_dc"
    elif 'coreless' in text_lower:
        extra["motor_type"] = "coreless"
    # Wireless
    if 'wireless' in text_lower or 'sem fio' in text_lower:
        extra["wireless"] = True
    # Bateria
    extra["has_battery"] = (
        'bateria' in text_lower or 'battery' in text_lower
        or 'powerbolt' in text_lower or 'acumulador' in text_lower
    )


def _extract_power_supply_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos de fontes de alimentação. Valores numéricos puros."""
    extra["equipment_model"] = _extract_psu_model(text)
    # Tensão de entrada
    for pattern in [
        r'(?:Power|Input|INPUT)\s*(?:input|voltage)?[:\s]+(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*V',
        r'(?:Input|INPUT)\s*Voltage[:\s]+(\d+\.?\d*)\s*V',
        r'(?:INPUT|Input)\s+(\d+\.?\d*)\s*V',
    ]:
        m = re.search(pattern, text, re.I)
        if m:
            if m.lastindex and m.lastindex >= 2:
                extra["input_voltage_min_v"] = float(m.group(1))
                extra["input_voltage_max_v"] = float(m.group(2))
            else:
                extra["input_voltage_v"] = float(m.group(1))
            break
    # Tensão de saída (min/max)
    for pattern in [
        r'(?:Volt|Voltage)\s*output[:\s]+(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)',
        r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*V\s*DC',
        r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*VDC',
        r'POWER\s*SUPPLY\s*\((\d+\.?\d*)\s*V',
    ]:
        m = re.search(pattern, text, re.I)
        if m:
            extra["output_voltage_min_v"] = float(m.group(1))
            if m.lastindex and m.lastindex >= 2:
                extra["output_voltage_max_v"] = float(m.group(2))
            break
    # Corrente de saída (prioriza "output" ou "delivering")
    for pat in [
        r'(?:output|delivering).*?(\d+\.?\d*)\s*A\b',
        r'(\d+\.?\d*)\s*A\s*(?:of\s*output|peak)',
    ]:
        m = re.search(pat, text, re.I)
        if m and float(m.group(1)) <= 20:
            extra["output_current_continuous_a"] = float(m.group(1))
            break
    # Corrente de pico
    m = re.search(r'(\d+\.?\d*)\s*A\s*peak', text, re.I)
    if m and float(m.group(1)) <= 30:
        extra["output_current_peak_a"] = float(m.group(1))
    # NITRO
    if 'nitro' in text_lower:
        extra["has_nitro"] = True
    # Footswitch
    if 'footswitch' in text_lower or 'foot switch' in text_lower or 'pedal' in text_lower:
        extra["has_footswitch"] = True
    # Display
    if 'display' in text_lower or 'lcd' in text_lower:
        extra["has_display"] = True
    # Timer
    if 'timer' in text_lower:
        extra["has_timer"] = True
    # Presets
    m = re.search(r'(\d+)\s*(?:memory\s*)?presets?', text_lower)
    if m:
        extra["memory_presets_count"] = int(m.group(1))
    # Peso
    for pat in [r'(\d+)\s*grams?\b', r'(\d+)\s*g\b']:
        m = re.search(pat, text, re.I)
        if m:
            w = int(m.group(1))
            if 30 <= w <= 5000:
                extra["weight_g"] = w
                break
    # Dimensões
    m = re.search(r'(\d+)\s*x\s*(\d+)\s*x\s*(\d+)\s*mm', text)
    if m:
        extra["length_mm"] = int(m.group(1))
        extra["width_mm"] = int(m.group(2))
        extra["height_mm"] = int(m.group(3))
    # Wireless
    if 'wireless' in text_lower or 'ble' in text_lower:
        extra["wireless"] = True
    # Proteção
    if 'overcurrent' in text_lower or 'short circuit' in text_lower:
        extra["has_overcurrent_protection"] = True


def _extract_battery_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos de baterias de máquinas. Valores numéricos puros."""
    extra["equipment_model"] = _extract_battery_model(text, text_lower)
    # Tensão de operação
    for pat in [r'Operating Voltage[:\s]+(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*V',
                r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)\s*V\s*DC']:
        m = re.search(pat, text, re.I)
        if m:
            extra["voltage_min_v"] = float(m.group(1))
            extra["voltage_max_v"] = float(m.group(2))
            break
    # Corrente
    m = re.search(r'Current[:\s]+.*?(\d+\.?\d*)\s*A\b', text, re.I)
    if m and float(m.group(1)) <= 5:
        extra["current_max_a"] = float(m.group(1))
    # Capacidade
    m = re.search(r'(\d+)\s*m[Aa]h', text)
    if m:
        extra["capacity_mah"] = int(m.group(1))
    # Tipo
    if 'li-ion' in text_lower or 'li ion' in text_lower:
        extra["battery_type"] = "Li-ion"
    elif 'lipo' in text_lower or 'li-po' in text_lower:
        extra["battery_type"] = "LiPo"
    # Recarregável
    if 'rechargeable' in text_lower or 'usb-c' in text_lower:
        extra["rechargeable"] = True
    # Display
    if 'oled' in text_lower or 'display' in text_lower:
        extra["has_display"] = True
    # Bluetooth
    if 'bluetooth' in text_lower:
        extra["has_bluetooth"] = True
    # Peso
    m = re.search(r'(\d+)\s*grams?\b', text, re.I)
    if m and 10 <= int(m.group(1)) <= 500:
        extra["weight_g"] = int(m.group(1))
    # Temperatura
    m = re.search(r'(\d+)\s*(?:to|–)\s*(\d+)\s*°\s*C', text)
    if m:
        extra["operating_temp_min_c"] = int(m.group(1))
        extra["operating_temp_max_c"] = int(m.group(2))


def _extract_battery_model(text: str, text_lower: str) -> str | None:
    models = ["PowerBolt II", "PowerBolt 2", "PowerBolt",
              "Lightning", "Rover R-1"]
    for model in sorted(models, key=lambda x: -len(x)):
        if model.lower() in text_lower:
            return model
    return None


def _extract_cartridge_fields(text: str, text_lower: str, extra: dict) -> None:
    """Campos de cartuchos/agulhas descartáveis."""
    # Tipos de cartucho — códigos e nomes por extenso
    type_map = {
        "RL": [r'(?:\d|^|\s)RL(?:\s|$|,|\.|\d)', r'round\s*liner'],
        "RS": [r'(?:\d|^|\s)RS(?:\s|$|,|\.|\d)', r'round\s*shader'],
        "M1": [r'(?:\d|^|\s)M1(?:\s|$|,|\.|\d)', r'(?<!\w)M1(?!\w)'],
        "RM": [r'(?:\d|^|\s)RM(?:\s|$|,|\.|\d)', r'round\s*magnum'],
        "CM": [r'(?:\d|^|\s)CM(?:\s|$|,|\.|\d)', r'curved\s*magnum'],
        "M": [r'(?:\d|^|\s)M(?:\s|$|,|\.|\d)', r'magnum(?!\s*1)'],
    }
    types = []
    for t, patterns in type_map.items():
        for pat in patterns:
            if re.search(pat, text, re.I):
                types.append(t)
                break
    if types:
        extra["cartridge_types"] = types
    # Diâmetro das agulhas
    diameters = set()
    for m in re.finditer(r'(\d+\.?\d+)\s*mm', text):
        d = float(m.group(1))
        if 0.10 <= d <= 0.50:
            diameters.add(d)
    if diameters:
        extra["needle_diameter_mm"] = sorted(diameters)
    # Material
    if 'aço' in text_lower or 'stainless' in text_lower:
        extra["needle_material"] = "Aço Inoxidável"
    if 'abs' in text_lower:
        extra["body_material"] = "ABS"
    # Membrana
    if 'membrana' in text_lower or 'membrane' in text_lower:
        extra["has_membrane"] = True
    # Esterilização
    if 'óxido de etileno' in text_lower or 'ethylene oxide' in text_lower:
        extra["sterilization_method"] = "Óxido de Etileno"
    # Validade
    m = re.search(r'(\d+)\s*anos?', text_lower)
    if m and 1 <= int(m.group(1)) <= 10:
        extra["sterility_shelf_life_years"] = int(m.group(1))
    # Unidades por caixa
    m = re.search(r'(\d+)\s*unidades?', text_lower)
    if m and int(m.group(1)) <= 100:
        extra["units_per_box"] = int(m.group(1))
    # Uso único
    if 'uso único' in text_lower or 'single use' in text_lower or 'proibido reprocessar' in text_lower:
        extra["single_use"] = True


def _extract_psu_model(text: str) -> str | None:
    models = ["TPS-500 X2", "TPS-500", "Machete MK-1", "Rover R-1",
              "Power Unit I", "Power Unit II", "Hover"]
    for model in sorted(models, key=lambda x: -len(x)):
        if model.lower() in text.lower():
            return model
    return None


def _extract_machine_model(text: str) -> str | None:
    """Extrai nome do modelo de máquina de tatuagem do texto.
    Ordenado por tamanho decrescente para evitar matches parciais
    (ex: 'Sol Nova Unlimited' antes de 'Sol Nova', 'Hawk Pen' antes de 'ONE')."""
    models = sorted([
        "Sol Nova Unlimited", "Sol Terra e Sol Luna", "Hawk Thunder",
        "Spektra Xion", "Linetion Sworder", "DK-W1 PRO",
        "P3 Pro Turbo", "Transverse Nano", "Dragonfly X2",
        "Linetion B2", "Flux Max", "Hawk Pen", "Sol Nova",
        "Hawk Spirit", "Hawk Thunder", "Sol Terra", "Sol Luna",
        "P2S Pro", "P3 Pro", "W1 PRO", "Alioth", "Alkaid",
        "Mizar", "Exo", "ONE", "Flux", "Bronc",
        "xXx", "W1", "P5", "EP10", "EP9",
    ], key=lambda x: -len(x))
    for model in models:
        words = model.lower().split()
        if len(words) >= 2:
            # Multi-palavra: todas as palavras devem aparecer como palavras inteiras no texto
            if all(re.search(r'\b' + re.escape(w) + r'\b', text.lower()) for w in words):
                return model
        elif re.search(r'\b' + re.escape(words[0]) + r'\b', text.lower()):
            return model
    return None


# ── Helpers ─────────────────────────────────────────────────────────────


def _extract_title(text: str, source_path: str) -> str:
    """Título do markdown (primeiro #) ou nome do arquivo."""
    match = re.search(r"^#\s+(.+)", text, re.MULTILINE)
    if match:
        return match.group(1).strip()[:120]
    import os
    return os.path.splitext(os.path.basename(source_path))[0][:120]


# Fabricantes de máquinas de tatuagem (prioridade máxima — testados primeiro)
_MACHINE_MANUFACTURERS: dict[str, str] = {
    "cheyenne": "Cheyenne / MT.DERM GmbH",
    "mt.derm": "Cheyenne / MT.DERM GmbH",
    "dklab": "DKLAB", "dk lab": "DKLAB",
    "dklabtattoo": "DKLAB", "feito por dklab": "DKLAB",
    "fk irons": "FK Irons",
    "electric ink": "Electric Ink",
    "ez": "EZ", "bronc": "Bronc",
    "inkmachines": "InkMachines", "musotoku": "Musotoku",
    "ava": "AVA", "bishop": "Bishop",
    "ghost": "Ghost",
}


def _detect_manufacturer(text_lower: str) -> str:
    """Detecta fabricante por palavra inteira (word boundary).
    Fabricantes de máquinas têm prioridade sobre componentes eletrônicos."""
    # 1. Fabricantes de máquinas (prioridade)
    for keyword, name in _MACHINE_MANUFACTURERS.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            return name
    # 2. Componentes eletrônicos (fallback)
    for keyword, name in _KNOWN_MANUFACTURERS.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            return name
    return ""


def _extract_part_number(text: str, text_lower: str, doc_type: str) -> str:
    """Extrai o part number principal do componente."""
    if doc_type == "datasheet_motor":
        # Ex: Series 2607 ... SR → "2607"
        match = re.search(r"series\s+([\d\s.]+(?:SR|CR|B|G))", text)
        if match:
            return match.group(1).strip()
    if doc_type.startswith("datasheet_"):
        # Ex: "INA219", "MLX90393", "MPU-6000"
        match = re.search(r"\b([A-Z]{2,6}[\d]{2,6}[-A-Za-z0-9]*)\b", text)
        if match:
            return match.group(1)[:30]
    return ""


def _extract_package(text_lower: str) -> str | None:
    """Detecta encapsulamento."""
    packages = {
        "soic": "SOIC", "sot-23": "SOT-23", "sot23": "SOT-23",
        "qfn": "QFN", "utdfn": "UTDFN", "dfn": "DFN",
        "bga": "BGA", "lga": "LGA", "qfp": "QFP",
        "tssop": "TSSOP", "msop": "MSOP", "sop": "SOP",
    }
    for keyword, pkg in packages.items():
        if keyword in text_lower:
            return pkg
    return None


def _extract_value(pattern: str, text: str) -> str | None:
    """Extrai o valor capturado por um grupo regex."""
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _strip_table_header(content: str) -> str | None:
    """Remove cabeçalho de tabela (QTD., VALOR, etc.) da primeira linha."""
    lines = content.strip().split("\n")
    if lines and re.match(r"^\s*(?:QTD\.|VALOR\s*UNIT\.?|VALOR\s*TOTAL|DESCRI[ÇC][ÃA]O)", lines[0]):
        lines = lines[1:]
    return "\n".join(lines).strip() or None


def _extract_section(text: str, header_pattern: str, max_lines: int = 8) -> str | None:
    """Extrai o texto após um cabeçalho de seção até a próxima quebra dupla, cabeçalho em maiúsculas, ou limite."""
    match = re.search(
        header_pattern + r"(.+?)(?:\n\n|\n\s*(?:[A-ZÀ-Ú][A-ZÀ-Ú\s]{4,}|QTD\.|VALOR\s*UNIT|VALOR\s*TOTAL)|\Z)",
        text, re.IGNORECASE | re.DOTALL
    )
    if match:
        content = match.group(1).strip().replace("\n", " ")
        return content[:500]
    return None


def _extract_number(pattern: str, text: str) -> float | None:
    """Extrai um valor numérico puro (ignora unidade)."""
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        raw = match.group(1).strip().replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return None
    return None
