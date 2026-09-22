"""Testes para o extrator de metadados de documentos."""

import pytest
from cous.knowledge.metadata import extract_metadata


class TestClassifyDocument:
    """Testes de classificação por palavras-chave (_classify)."""

    def test_datasheet_motor_classification(self):
        text = "nominal voltage 12V, stall torque 0.5 Nm, no-load speed 10000 rpm"
        result = extract_metadata(text)
        assert result["document_type"] == "datasheet_motor"
        assert result["category"] == "motor"

    def test_datasheet_sensor_current_power(self):
        text = "current shunt 0.1 ohm, bus voltage 3.3V, power monitor with zero-drift"
        result = extract_metadata(text)
        assert result["document_type"] == "datasheet_sensor"
        assert result["category"] == "current_power"

    def test_datasheet_sensor_magnetic(self):
        text = "triaxis hall technology, magnetic flux density up to 50mT, hall sensor"
        result = extract_metadata(text)
        assert result["document_type"] == "datasheet_sensor"
        assert result["category"] == "magnetic"

    def test_datasheet_sensor_imu(self):
        text = "gyroscope and accelerometer for motion processing, angular rate 2000dps"
        result = extract_metadata(text)
        assert result["document_type"] == "datasheet_sensor"
        assert result["category"] == "imu"

    def test_datasheet_interface_converter(self):
        text = "usb to uart bridge, baud rate up to 3Mbps, flow control RTS/CTS"
        result = extract_metadata(text)
        assert result["document_type"] == "datasheet_interface"
        assert result["category"] == "converter"

    def test_datasheet_passive_resistor(self):
        text = "power metal strip shunt resistor, current sense resistor 5 milliohm"
        result = extract_metadata(text)
        assert result["document_type"] == "datasheet_passive"
        assert result["category"] == "resistor"

    def test_service_order_classification(self):
        text = "cliente: João\ncnpj / cpf: 123.456.789-00\nordem de serviço #001"
        result = extract_metadata(text)
        assert result["document_type"] == "service_order"
        assert result["category"] == "os"

    def test_book_classification(self):
        text = "copyright © 2024, isbn 978-85-1234-567-8, editora Blucher, ficha catalográfica"
        result = extract_metadata(text)
        assert result["document_type"] == "book"
        assert result["category"] == "engineering_book"

    def test_measurement_classification(self):
        text = "## cabecalho - fabricante: FK Irons\n## resumo tecnico\nhall: 7260 RPM"
        result = extract_metadata(text)
        assert result["document_type"] == "measurement"
        assert result["category"] == "measurement"

    def test_academic_classification(self):
        text = "trabalho de conclusão de curso\norientador: Prof. Dr. Silva\nuniversidade: USP"
        result = extract_metadata(text)
        assert result["document_type"] == "academic"
        assert result["category"] == "academic"

    def test_generic_document_fallback(self):
        text = "relatório de manutenção preventiva de equipamento industrial"
        result = extract_metadata(text)
        assert result["document_type"] == "generic"
        assert result["category"] == "general"

    def test_machine_manual_classification(self):
        text = "máquina de tatuagem com frequência de perfuração ajustável e saliência da agulha regulável"
        result = extract_metadata(text)
        assert result["document_type"] == "machine_manual"
        assert result["category"] == "tattoo_machine"

    def test_single_keyword_not_enough(self):
        """Apenas 1 palavra-chave não deve bastar para classificar (threshold=2)."""
        text = "stall torque 0.5 Nm"  # só 1 keyword do motor
        result = extract_metadata(text)
        assert result["document_type"] == "generic"


class TestExtractFields:
    """Testes de extração de campos por tipo de documento."""

    def test_motor_datasheet_extracts_fields(self):
        text = (
            "nominal voltage 12V, stall torque 0.5 Nm\n"
            "no-load speed 10000 rpm, phase resistance 0.8 ohm\n"
            "fabricante: Faulhaber\n"
            "modelo: 2232U012SR"
        )
        result = extract_metadata(text)
        assert result["manufacturer"] == "Faulhaber"
        extra = result["extra"]
        assert "nominal_voltage" in extra
        assert "stall_torque" in extra

    def test_measurement_extracts_fields(self):
        text = (
            "## cabecalho - fabricante: DKLAB\n"
            "## resumo tecnico\n"
            "modelo: X1"
        )
        result = extract_metadata(text)
        assert result["document_type"] == "measurement"
        assert result["manufacturer"] == "DKLAB"
        assert result["model"] == "X1"

    def test_service_order_extracts_fields(self):
        text = (
            "cliente: João Silva\n"
            "cnpj / cpf: 123.456.789-00\n"
            "cel: (11) 99999-9999\n"
            "endereço: Rua das Máquinas\n"
            "ordem de serviço #001\n"
            "n° de série: SN-001\n"
            "marca: FK Irons\n"
            "modelo: Phantom\n"
            "data de entrada: 01/01/2025\n"
            "técnico: Carlos"
        )
        result = extract_metadata(text)
        assert result["document_type"] == "service_order"
        extra = result["extra"]
        assert "equipment_brand" in extra
        assert extra["service_order_number"] == "001"
        assert extra["equipment_serial"] == "SN-001"

    def test_service_order_preserves_compound_serial(self):
        text = (
            "cliente: Artefato Tattoo Supply\n"
            "cnpj / cpf: 19.926.665/0001-03\n"
            "cel: 31999323961\n"
            "endereco: Avenida Afonso Pena\n"
            "ordem de servico: 1119\n"
            "numero de serie: EP10757 040523\n"
        )

        result = extract_metadata(text)

        assert result["document_type"] == "service_order"
        assert result["extra"]["service_order_number"] == "1119"
        assert result["extra"]["equipment_serial"] == "EP10757 040523"

    def test_service_order_serial_strips_adjacent_color_column(self):
        text = (
            "cliente: Matheus\n"
            "cnpj / cpf: 123.456.789-00\n"
            "cel: 31999999999\n"
            "endereco: Rua das Maquinas\n"
            "ordem de servico: 1125\n"
            "n° de série: W1NP2403464                               COR: DOURADA\n"
        )
        result = extract_metadata(text)
        assert result["extra"]["equipment_serial"] == "W1NP2403464"

    def test_service_order_extracts_markdown_list_fields(self):
        text = (
            "# Ordem de Servico 1119\n\n"
            "- Cliente: Artefato Tattoo Supply\n"
            "- CNPJ / CPF: 19.926.665/0001-03\n"
            "- Cel: 31999323961\n"
            "- Endereco: Avenida Afonso Pena\n"
            "- Ordem de servico: 1119\n"
            "- Marca: AVA\n"
            "- Modelo: EP10\n"
            "- Numero de serie: EP10757 040523\n"
            "- Data de entrada: 06/07/2026\n"
            "- Tecnico responsavel: Selecione\n"
        )

        result = extract_metadata(text)
        extra = result["extra"]

        assert extra["equipment_brand"] == "AVA"
        assert extra["equipment_model"] == "EP10"
        assert extra["equipment_serial"] == "EP10757 040523"
        assert extra["service_date"] == "06/07/2026"
        assert extra["technician"] == "Selecione"

    def test_book_extracts_publisher(self):
        text = (
            "copyright © 2024, isbn 978-85-1234-567-8\n"
            "editora Blucher\n"
            "ficha catalográfica\n"
            "impresso no brasil"
        )
        result = extract_metadata(text)
        assert result["document_type"] == "book"
        assert result["manufacturer"] == "Blucher"

    def test_empty_extra_cleaned(self):
        """Campos vazios em extra devem ser removidos."""
        text = "relatório genérico sem metadados específicos"
        result = extract_metadata(text)
        assert result["extra"] == {}


class TestEdgeCases:
    """Casos de borda: entradas vazias, texto mínimo, case-insensitivity."""

    def test_empty_text_does_not_raise(self):
        result = extract_metadata("")
        assert result["document_type"] == "generic"

    def test_whitespace_only_text(self):
        result = extract_metadata("   \n  \t  ")
        assert result["document_type"] == "generic"

    def test_keyword_case_insensitive(self):
        text = "NOMINAL VOLTAGE 12V, STALL TORQUE 0.5 Nm"
        result = extract_metadata(text)
        assert result["document_type"] == "datasheet_motor"

    def test_returns_dict_structure(self):
        result = extract_metadata("qualquer texto")
        assert isinstance(result, dict)
        assert "document_type" in result
        assert "category" in result
        assert "title" in result
        assert "manufacturer" in result
        assert "model" in result
        assert "extra" in result
