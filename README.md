# ECM Control Module & CAN Diagnostic Tool 🏎️🔌

Este projeto consiste em uma plataforma de simulação e diagnóstico automotivo em tempo real, desenvolvida em Python (Tkinter). O sistema emula o comportamento de uma Unidade de Controle do Motor (ECM) e a sua interação com outros módulos periféricos através de um barramento de rede CAN (Controller Area Network), utilizando o conceito de arquitetura multiplexada baseada nos padrões internacionais **ISO 15765** e **SAE J1939** (OBD-II).

---

# 🛠️ Como Instalar e Rodar no Visual Studio Code (VS Code)

Se você clonou o repositório e precisa preparar o ambiente para rodar a aplicação, siga o passo a passo abaixo direto no seu VS Code:

### 1. Pré-requisitos
Certifique-se de ter o **Python 3** instalado na sua máquina e a extensão do Python ativa no seu VS Code. 

*(Nota: A biblioteca **Tkinter** já vem instalada por padrão junto com o Python no Windows. Caso use Linux, pode ser necessário rodar `sudo apt-get install python3-tk`).*

### 2. Abrir o Terminal no VS Code
Com o projeto aberto na tela do seu VS Code, abra o terminal integrado utilizando o atalho:
* **Windows/Linux:** `Ctrl + Shift + '` (ou vá no menu superior: **Terminal > New Terminal**).

### 3. Instalar as Dependências (Pillow e PySerial)
No terminal que se abriu na parte inferior da tela, digite ou cole o comando abaixo e aperte **Enter**:

```bash
pip install Pillow pyserial

O simulador possui dois modos de operação principais:
1. **Modo Real (Hardware-in-the-Loop):** Interface física via porta Serial, comunicando-se com microcontroladores externos (como ESP32/Arduino) acoplados a transceptores CAN (TJA1050). Neste modo, a ECM recebe os sinais analógicos tratados pelos nós de entrada, calcula as estratégias e devolve via barramento os comandos de atuação para os periféricos físicos.
2. **Modo Virtual (Software Emulation):** Ambiente de simulação completo onde o próprio software executa rotinas independentes em segundo plano (*Multithreading*) para emular o tráfego de dados, as respostas e as regras de negócio dos outros nós ausentes da bancada.

---

## 📇 Matriz de Comunicação da Rede CAN (Contrato de Mensagens)

Para que o ecossistema funcione em perfeita sincronia (seja com placas reais ou simuladas), o barramento CAN segue rigorosamente o seguinte mapeamento de IDs, fluxos e responsabilidades:

| ID CAN | Módulo Emissor (Quem Envia) | Módulo Receptor (Quem Lê) | Conteúdo do Payload (O que a mensagem diz) | Função e Regra de Negócio Automotiva / Robótica |
| :---: | :--- | :--- | :--- | :--- |
| **`0x100`** | Nó do Pedal (Acelerador) | **Sua ECM** | Porcentagem de abertura do pedal (ex: `0x2D` = 45%) | Informa a intenção de aceleração do motorista (Sinal APP). |
| **`0x150`** | Nó do Ultrassom | **Sua ECM** | Distância medida em centímetros (ex: `0x1E` = 30cm) | Detecta aproximação de obstáculos para segurança ativa e leitura de terreno. |
| **`0x200`** | Nó da BCM (Imobilizador) | **Sua ECM** | Status de autorização (`ON` / `OFF`) | Libera a partida do motor após checar a criptografia da chave. |
| **`0x250`** | Módulo de Bateria / BMS | **Sua ECM** | Tensão atual do sistema em Volts (ex: `0x6E` = 11.0V) | Monitora a saúde elétrica da alimentação para proteção de subtensão. |
| **`0x300`** | **Sua ECM** | Nó do TBI (Borboleta) | Comando PWM de abertura da borboleta (0% a 100%) | Atua diretamente no motor do corpo de borboleta para admitir ar. |
| **`0x101`** | **Sua ECM** | Nó do Painel (Cluster) | Rotação (RPM) e Temperatura (°C) do motor | Atualiza a posição física ou gráfica dos ponteiros no painel. |
| **`0x350`** | Nó da TCM (Câmbio) | **Sua ECM** | Marcha engatada (`D1`, `D2`, `LIMP`) | Sincroniza a força do motor com o estado atual da transmissão. |
| **`0x7DF`** | Scanner de Diagnóstico | **Sua ECM** | Requisição de PIDs padrão OBD-II (`01 0C 05`) | Ferramenta externa solicitando dados de fluxo (frequência e calor). |
| **`0x7E8`** | **Sua ECM** | Scanner de Diagnóstico | Resposta com valores físicos calculados dos sensores | Retorna o status da bomba, pressão em bar e temperatura em °C. |

---

## ⚠️ Gerenciamento de Falhas e Estados de Emergência

O simulador monitora o estado de saúde da rede CAN e dos sensores continuamente. Abaixo estão detalhadas as ações exatas que o sistema toma quando um módulo é desconectado ou um sensor atinge limites críticos de segurança:

### 1. Falha no Módulo BCM (Imobilizador Offline)
* **Comportamento na Interface:** O botão de partida muda o status para `IMOBILIZADOR ATIVO` (com fundo vermelho) e a chave de ignição física é desabilitada pelo software.
* **Ação no Motor:** * Se o motor já estava desligado: A partida é 100% bloqueada.
  * Se o motor já estava funcionando: O sistema entra em modo de segurança, limitando a rotação máxima em **2000 RPM** para permitir que o veículo seja movido, mas impedindo acelerações plenas.

### 2. Falha no Módulo TCM (Câmbio Automático Offline)
* **Comportamento na Interface:** O indicador de marcha no painel muda de `D1/D2` para `LIMP` (piscando em vermelho).
* **Ação no Motor:** A ECM entra em **Limp Mode** de transmissão. Como a central perde a referência de carga da caixa de câmbio, o torque é severamente reduzido: a rotação máxima cai automaticamente em **40%** e a leitura do sensor MAP é limitada para proteger os componentes mecânicos contra quebras por tranco.

### 3. Falha no Módulo Cluster (Painel Offline)
* **Comportamento na Interface:** O indicador visual digital exibe a mensagem de erro `ERR: CAN TIMEOUT` e os ponteiros gráficos caem imediatamente para zero.
* **Ação no Motor:** O motor continua funcionando para não comprometer a locomoção, mas a ECM registra um código de falha grave na rede por perda de comunicação com o painel de instrumentos.

### 4. Sobrecarga de Pressão (MAP > 1.8 bar)
* **Comportamento na Interface:** O sniffer dispara o alerta vermelho `[ECM ACTUATOR] OVERPRESSURE DETECTED!`.
* **Ação no Motor:** A ECM corta o sinal da **Bomba Eletrônica de Combustível (`STATUS: OFF`)** e derruba o giro do motor instantaneamente para **900 RPM** (marcha lenta). O fluxo de combustível (representado graficamente pela animação azul) congela no frame zero na tela, simulando o corte elétrico do relé da bomba para evitar a quebra do motor por excesso de pressão de turbo.

### 5. Emergência Térmica (Temperatura >= 103°C)
* **Comportamento na Interface:** O topo do painel pisca o aviso crítico `🛑 PROTEÇÃO TÉRMICA ATIVA 🛑`.
* **Ação no Motor:** A ECM entra em modo de proteção contra superaquecimento. Ela ignora completamente a posição do pedal do acelerador (mesmo se o motorista estiver com o pé cravado em 100%) e força o motor a trabalhar estritamente a **900 RPM** até que o bloco resfrie. O ponteiro de temperatura do painel trava no pico (**94**) para garantir que o aviso visual crítico não suma durante a queda de giro.

### 6. Alerta de Proximidade Crítica (Ultrassom < 30 cm)
* **Comportamento na Interface:** O topo da tela pisca o aviso `🛑 ALERTA DE COLISÃO - EMBARGO ULTRASSOM 🛑` e o sniffer gera logs periódicos de interrupção de segurança.
* **Ação no Motor:** O software simula um sistema de **Frenagem Autônoma de Emergência (AEB)** ou bloqueio de transposição. A ECM corta imediatamente o funcionamento da bomba de combustível e zera a rotação do motor, impedindo colisões estruturais com barreiras físicas ou quedas bruscas de degraus detectados na telemetria.

### 7. Proteção por Subtensão Elétrica (Bateria < 11.0V)
* **Comportamento na Interface:** A barra de status principal exibe `🛑 FALHA ELÉTRICA: SUBTENSAO BATERIA 🛑` e gera o alerta `[BATTERY CRITICAL]` no painel do sniffer.
* **Ação no Motor:** A central ativa a estratégia de **Under-voltage Lockout**. Como microcontroladores e transceptores CAN exigem tensões estáveis para evitar comportamentos imprevisíveis e corrupção de dados na rede, a ECM bloqueia completamente o acionamento dos atuadores e impede a ignição enquanto a energia do sistema estiver degradada.

---

## 🛠️ Estratégias de Fail-Safe e Computação de Injeção

Além dos modos de falha, a central executa cálculos matemáticos de tempo real para o gerenciamento de mapas:

* **Gerenciamento de Malhas de Injeção (Mapa ECM):** O software possui uma matriz bidimensional dinâmica contendo o Tempo de Injeção em milissegundos ($ms$) cruzando dados de Carga (MAP) vs Rotação (RPM). Se a rede CAN operar sem falhas, o mapa em malha normal é executado; se houver perda de nós essenciais (como BCM ou TCM em `OFFLINE`), o mapa é substituído em tempo real por tabelas de calibração seguras de emergência (*Limp Mode*).

---

## 🖥️ Decodificação do Sniffer de Rede (CAN Logs)

O monitor da aplicação atua como um scanner automotivo profissional, traduzindo os frames hexadecimais nativos e pacotes de transmissão da rede CAN para mensagens legíveis em português e em tempo real:

* `SCANNER (0x7DF) ➔ Solicitando leitura de Rotação (RPM) e Temperatura do Motor.` (Requisição global OBD-II).
* `ECM INJEÇÃO (0x7E8) ➔ Retornando dados ao Scanner: Bomba=ON | MAP=0.4bar | Temp=85°C` (Resposta física da central).
* `IMOBILIZADOR BCM (0x200) ➔ Status da Ignição Chave: ON | Autenticação CAN OK` (Validação de partida).
* `TRANSMISSÃO TCM (0x350) ➔ Monitoramento de Câmbio Ativo: Marcha Atual = D1` (Sincronismo de torque).

---

## 🚀 Tecnologias Utilizadas

* **Linguagem:** Python 3
* **Interface Gráfica:** Tkinter / TTK
* **Processamento de Imagem:** Pillow (PIL) para desmembramento e renderização dinâmica de frames de GIFs automotivos reativos.
* **Comunicação:** PySerial (para integração com microcontroladores em Modo Real).
* **Arquitetura:** Concorrência via Threads e filas thread-safe (`queue`).