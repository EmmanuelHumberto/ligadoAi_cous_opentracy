# Histórico de Filtros de Classificação — metadata.py

> Documenta todos os tipos de documento, palavras-chave e fabricantes detectados pelo extrator de metadados do Cous.

---

## Tipos de documento e palavras-chave (threshold=2)

| # | document_type | category | Palavras-chave |
|---|---------------|----------|----------------|
| 1 | `datasheet_motor` | `motor` | `nominal voltage`, `stall torque`, `no-load speed`, `back-emf constant`, `torque constant`, `rotor inductance`, `speed constant` |
| 2 | `datasheet_sensor` | `current_power` | `current shunt`, `power monitor`, `bus voltage`, `shunt voltage`, `current register`, `power register`, `zero-drift`, `bidirectional` |
| 3 | `datasheet_sensor` | `magnetic` | `triaxis`, `magnetic node`, `hall technology`, `magnetic flux density`, `magnetic field sensor`, `hall sensor` |
| 4 | `datasheet_sensor` | `imu` | `gyroscope`, `accelerometer`, `motion processing`, `motion tracking`, `angular rate`, `digital motion processor`, `invensense` |
| 5 | `datasheet_interface` | `converter` | `usb to uart`, `usb serial`, `baud rate`, `uart interface`, `flow control`, `rs-232` |
| 6 | `datasheet_interface` | `io_expander` | `gpio expander`, `io expander`, `i2c gpio`, `parallel io` |
| 7 | `datasheet_passive` | `resistor` | `power metal strip`, `shunt resistor`, `current sense resistor`, `surface mount resistor`, `wirewound resistor` |
| 8 | `service_order` | `os` | `cliente:`, `cnpj / cpf:`, `cel:`, `endereço:`, `ordem de serviço`, `os system` |
| 9 | `measurement` | `measurement` | `## cabecalho - fabricante:`, `## resumo tecnico` |
| 10 | `academic` | `academic` | `trabalho de conclusão de curso`, `dissertação`, `tese`, `monografia`, `orientador`, `universidade`, `faculdade`, `programa de pós-graduação`, `departamento acadêmico` |
| 11 | `book` | `engineering_book` | `copyright ©`, `isbn`, `ficha catalográfica`, `editora`, `edição`, `impresso no brasil`, `tradução autorizada`, `todos os direitos reservados` |
| 12 | `battery` | `battery` | `machine battery`, `usb-c battery`, `li-ion`, `lipo`, `battery capacity`, `mah`, `rechargeable battery`, `powerbolt`, `lightning battery`, `bateria`, `acumulador`, `battery cell`, `removable battery` |
| 13 | `power_supply` | `power_supply` | `power supply`, `fonte de alimentação`, `footswitch`, `voltage output`, `power input`, `powerpack`, `overcurrent`, `memory preset`, `nitro`, `battery pack`, `charger bay`, `power cord`, `output current`, `short circuit` |
| 14 | `machine_manual` | `tattoo_machine` | `saliência da agulha`, `frequência de perfuração`, `máquina de tatuagem`, `tattoo machine`, `needle cartridge`, `instruções de uso`, `instruções de segurança`, `modo de usar`, `esterilização`, `autoclave`, `tatuagem`, `tattoo`, `needle depth`, `stroke length`, `give adjustment`, `operating voltage`, `wireless tattoo`, `power bolt`, `tattooing machine`, `cartridge needles`, `safety membrane`, `máquina`, `caneta`, `agulha`, `cartucho`, `needle`, `cartridge` |
| 15 | `generic` | `general` | (fallback — qualquer documento que não bata 2+ keywords acima) |

---

## Ordem de classificação (primeiro match vence)

| Prioridade | Tipo | Nota |
|:---:|------|------|
| 1-7 | datasheets (motor, sensor, interface, passivo) | Específicos, baixo risco de falso positivo |
| 8 | service_order | Formato de OS |
| 9 | measurement | Formato de medição do Cous |
| 10 | academic | Antes de book e machine_manual — artigos com citações não viram book |
| 11 | book | ISBN, editora, copyright |
| 12 | battery | Antes de power_supply — baterias não viram fontes |
| 13 | power_supply | Antes de machine_manual — fontes não viram máquinas |
| 14 | machine_manual | Último tipo específico |
| 15 | generic | Fallback |

---

## Fabricantes detectados

### Máquinas de tatuagem (prioridade máxima)

| Palavra-chave | Fabricante |
|---------------|------------|
| `cheyenne` | Cheyenne / MT.DERM GmbH |
| `mt.derm` | Cheyenne / MT.DERM GmbH |
| `dklab`, `dk lab`, `dklabtattoo`, `feito por dklab` | DKLAB |
| `fk irons` | FK Irons |
| `electric ink` | Electric Ink |
| `ez` | EZ |
| `bronc` | Bronc |
| `inkmachines` | InkMachines |
| `musotoku` | Musotoku |
| `ava` | AVA |
| `bishop` | Bishop |

### Componentes eletrônicos (fallback)

| Palavra-chave | Fabricante |
|---------------|------------|
| `faulhaber` | Faulhaber |
| `maxon` | Maxon |
| `portescap` | Portescap |
| `texas instruments` | Texas Instruments |
| `melexis` | Melexis |
| `invensense` | InvenSense |
| `vishay` | Vishay |
| `wch` | WCH |
| `diodes` | Diodes Inc. |
| `allegro` | Allegro MicroSystems |
| `stmicroelectronics` | STMicroelectronics |

### Cartuchos / acessórios (fallback)

| Palavra-chave | Fabricante |
|---------------|------------|
| `krieg tattoo` | Krieg Tattoo |
| `harpia` | Harpia |
| `onskin` | ONSKIN |
| `white head` | White Head |
| `iron works` | Iron Works |

---

## Instituições acadêmicas detectadas

UTFPR, UFSM, USP, UNICAMP, UFSC, UFMG, UFRJ, UNESC, Faculdade Doctum

---

## Editoras detectadas

McGraw-Hill, Pearson, Prentice Hall, Bookman, Artmed, LTC, Blucher, Cengage Learning, Saraiva, Alta Books, Novatec, Ciência Moderna
