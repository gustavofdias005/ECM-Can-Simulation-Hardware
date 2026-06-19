import json
import os
import queue
import serial
import serial.tools.list_ports
import threading
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageSequence, ImageDraw

# Scale global para o zoom das imagens (S=4.0)
S = 4.0
CONFIG_FILE = "config_can.json"
COR_FUNDO = "#222034"
COR_PAINEL = "#1a1926"
COR_TEXTO = "#cbdbfc"
COR_LARANJA = "#df7126"
COR_VERDE = "#99e550"
COR_AZUL = "#5fcde4"
COR_VERMELHO = "#ac3232"
COR_LED_OFF = "#2f3142"


def carregar_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "start_byte": "0x20",
        "end_byte": "0x1f",
        "id_pedal": "0x100",
        "id_rpm": "0x101",
        "id_map": "0x200",
        "id_temp": "0x201",
        "id_tbi": "0x300",
        "id_ultrassom": "0x150",
        "id_bat": "0x250"
    }


def salvar_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)


config_atual = carregar_config()

# Estado dinâmico do motor e da rede CAN simulada com novos sensores
motor = {
    "pedal_app": 0,
    "borboleta_tbi": 0,
    "rpm": 0,
    "map": 1.0,
    "temp_agua": 25,
    "bomba": "OFF",
    "ignicao": "OFF",
    "modo": "REAL",
    "simulacao_ativa": False,
    "marcha": "D1",
    "bcm_status": "ONLINE",
    "cluster_status": "ONLINE",
    "tcm_status": "ONLINE",
    # Novos Sensores adicionados ao Core
    "distancia_ultra": 100,  # em cm
    "tensao_bateria": 12.6,  # em V
}

fila_ui = queue.Queue()


def ui_call(func, *args, **kwargs):
    fila_ui.put((func, args, kwargs))


def carregar_imagem_segura(caminho):
    try:
        img_original = Image.open(caminho)
        if getattr(img_original, "is_animated", False):
            return [f.copy().convert("RGBA") for f in ImageSequence.Iterator(img_original)], True
        return img_original.convert("RGBA"), False
    except FileNotFoundError:
        img_erro = Image.new("RGBA", (128, 128), color=COR_VERMELHO)
        d = ImageDraw.Draw(img_erro)
        d.line((0, 0, 128, 128), fill="#fff", width=4)
        d.line((0, 128, 128, 0), fill="#fff", width=4)
        return img_erro, False


assets_originais = {
    "pedal": carregar_imagem_segura("imagens/pedal_acelerador.gif"),  
    "map": carregar_imagem_segura("imagens/sensor_map.gif"),          
    "bomba": carregar_imagem_segura("imagens/bomba_combustivel.gif"), 
    "modulo": carregar_imagem_segura("imagens/modulo_ecm.gif"),       
    "temp": carregar_imagem_segura("imagens/sensor_temp.gif"),        
    "borboleta": carregar_imagem_segura("imagens/corpo_borboleta.gif"),
}

cache_tk = {}
root = tk.Tk()
root.title("ECM Control Module & CAN Diagnostic Tool")
root.attributes("-fullscreen", True)
root.configure(bg=COR_FUNDO)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen", False))

container = tk.Frame(root)
container.pack(fill="both", expand=True)
aba_dash = tk.Frame(container, bg=COR_FUNDO)
aba_config = tk.Frame(container, bg=COR_PAINEL)
aba_usb = tk.Frame(container, bg=COR_PAINEL)
for aba in (aba_dash, aba_config, aba_usb):
    aba.place(relx=0, rely=0, relwidth=1, relheight=1)
lista_abas = [aba_dash, aba_config, aba_usb]
aba_atual_idx = 0


def alternar_abas(event=None):
    global aba_atual_idx
    aba_atual_idx = (aba_atual_idx + 1) % len(lista_abas)
    lista_abas[aba_atual_idx].tkraise()


root.bind("<Tab>", alternar_abas)


def alterar_escala(delta):
    global S
    S = max(0.5, min(5.0, S + delta))


root.bind(".", lambda e: alterar_escala(0.25))
root.bind(",", lambda e: alterar_escala(-0.25))

top_bar = tk.Frame(aba_dash, bg=COR_PAINEL, highlightbackground=COR_LARANJA, highlightthickness=1)
top_bar.place(relx=0, rely=0, relwidth=1, relheight=0.1)
lbl_status_usb = tk.Label(top_bar, text="USB/TJA1050: OFFLINE", bg=COR_PAINEL, fg=COR_VERMELHO, font=("Courier", 10, "bold"))
lbl_status_usb.place(relx=0.02, rely=0.5, anchor="w")
lbl_modo = tk.Label(top_bar, text="MODO: REAL", bg=COR_PAINEL, fg=COR_TEXTO, font=("Courier", 10, "bold"))
lbl_modo.place(relx=0.32, rely=0.5, anchor="center")
lbl_rpm_top = tk.Label(top_bar, text="ROTAÇÃO: 0 RPM", bg=COR_PAINEL, fg=COR_VERDE, font=("Courier", 10, "bold"))
lbl_rpm_top.place(relx=0.98, rely=0.5, anchor="e")
btn_modo_virtual = tk.Button(top_bar, text="MODO VIRTUAL", bg=COR_AZUL, fg=COR_FUNDO, font=("Arial", 8, "bold"))
btn_modo_virtual.place(relx=0.5, rely=0.5, anchor="center")

# Layout de 6 colunas proporcionais
matriz_frame = tk.Frame(aba_dash, bg=COR_FUNDO)
matriz_frame.place(relx=0, rely=0.1, relwidth=1, relheight=0.65)
colunas = []
titulos = ["PEDAL (APP)", "TELEMETRIA SENS", "BOMBA ELETRÔNICA", "ECM CENTRAL", "CLUSTER / TEMP", "TCM / TBI"]
lbls_imagens, lbls_valores = [], []
for i in range(6):
    f = tk.Frame(matriz_frame, bg=COR_FUNDO, highlightbackground=COR_PAINEL, highlightthickness=1)
    f.place(relx=i * 0.166, rely=0, relwidth=0.166, relheight=1)
    colunas.append(f)
    tk.Label(f, text=titulos[i], bg=COR_FUNDO, fg=COR_LARANJA, font=("Courier", 9, "bold")).place(relx=0.5, rely=0.05, anchor="center")
    lbl_img = tk.Label(f, bg=COR_FUNDO)
    lbl_img.place(relx=0.5, rely=0.4, anchor="center")
    lbls_imagens.append(lbl_img)
    lbl_v = tk.Label(f, text="-", bg=COR_FUNDO, fg=COR_TEXTO, font=("Arial", 9, "bold"), justify="center")
    lbl_v.place(relx=0.5, rely=0.7, anchor="center")
    lbls_valores.append(lbl_v)

leds_rede = {}
btns_pane = {}


def criar_led_pane(coluna, modulo, relx):
    canvas = tk.Canvas(coluna, width=18, height=18, bg=COR_FUNDO, highlightthickness=0)
    canvas.place(relx=relx, rely=0.12, anchor="center")
    canvas.create_oval(3, 3, 15, 15, fill=COR_LED_OFF, outline="#000", tags="lamp")
    leds_rede[modulo] = canvas
    btn = tk.Button(coluna, text="ONLINE", bg=COR_VERDE, fg="#000", font=("Arial", 7, "bold"), command=lambda m=modulo: alternar_pane_rede(m))
    btn.place(relx=0.5, rely=0.12, relwidth=0.46, relheight=0.07, anchor="center")
    btns_pane[modulo] = btn


criar_led_pane(colunas[1], "bcm", 0.15)       
criar_led_pane(colunas[4], "cluster", 0.15)   
criar_led_pane(colunas[5], "tcm", 0.15)       

# Sliders do Modo Virtual realocados para simular os novos sensores
tk.Label(colunas[0], text="PEDAL", bg=COR_FUNDO, fg=COR_TEXTO, font=("Arial", 7)).place(relx=0.5, rely=0.75, anchor="center")
scale_pedal = tk.Scale(colunas[0], from_=0, to=100, orient="horizontal", bg=COR_FUNDO, fg=COR_AZUL, highlightthickness=0, showvalue=0, command=lambda v: atualizar_calculos_motor(v))
scale_pedal.place(relx=0.1, rely=0.77, relwidth=0.8, relheight=0.07)

tk.Label(colunas[0], text="SIMULADOR DISTÂNCIA (Ultrassom)", bg=COR_FUNDO, fg=COR_TEXTO, font=("Arial", 7)).place(relx=0.5, rely=0.86, anchor="center")
scale_ultra = tk.Scale(colunas[0], from_=10, to=150, orient="horizontal", bg=COR_FUNDO, fg=COR_AZUL, highlightthickness=0, showvalue=0, command=lambda v: atualizar_valores_virtuais_sensores())
scale_ultra.set(100)
scale_ultra.place(relx=0.1, rely=0.88, relwidth=0.8, relheight=0.06)

tk.Label(colunas[0], text="SIMULADOR BATERIA (V)", bg=COR_FUNDO, fg=COR_TEXTO, font=("Arial", 7)).place(relx=0.5, rely=0.94, anchor="center")
scale_bat = tk.Scale(colunas[0], from_=9.0, to=14.5, resolution=0.1, orient="horizontal", bg=COR_FUNDO, fg=COR_AZUL, highlightthickness=0, showvalue=0, command=lambda v: atualizar_valores_virtuais_sensores())
scale_bat.set(12.6)
scale_bat.place(relx=0.1, rely=0.95, relwidth=0.8, relheight=0.05)

btn_ignicao = tk.Button(colunas[3], text="IGNIÇÃO (CHAVE)", bg=COR_VERMELHO, fg="#fff", font=("Arial", 8, "bold"), command=lambda: alternar_ignicao())
btn_ignicao.place(relx=0.1, rely=0.8, relwidth=0.8, relheight=0.15)
lbl_marcha = tk.Label(colunas[5], text="MARCHA: D1", bg=COR_FUNDO, fg=COR_AZUL, font=("Courier", 11, "bold"))
lbl_marcha.place(relx=0.5, rely=0.9, anchor="center")

painel_inferior = tk.Frame(aba_dash, bg="#000")
painel_inferior.place(relx=0, rely=0.75, relwidth=1, relheight=0.25)

lista_sniffer = tk.Listbox(painel_inferior, bg="#000", fg=COR_AZUL, bd=0, font=("Courier", 8))
lista_sniffer.place(relx=0.01, rely=0.1, relwidth=0.53, relheight=0.8)

frame_mapa = tk.Frame(painel_inferior, bg=COR_PAINEL, bd=1, relief="sunken")
frame_mapa.place(relx=0.56, rely=0.08, relwidth=0.42, relheight=0.84)

tk.Label(frame_mapa, text="MAPA TEMPO DE INJEÇÃO ECM (ms) vs CARGA MAP / RPM", bg=COR_PAINEL, fg=COR_LARANJA, font=("Courier", 7, "bold")).grid(row=0, column=0, columnspan=5, pady=2)

faixas_map = ["1.6 bar", "1.2 bar", "0.8 bar", "0.4 bar"]
faixas_rpm = ["1000", "2500", "4000", "5500"]

mapa_valores_normal = [
    ["4.2", "5.5", "6.8", "8.2"],  
    ["3.1", "4.2", "5.4", "6.7"],
    ["2.2", "3.0", "4.1", "5.2"],
    ["1.4", "2.1", "2.8", "3.9"]   
]

mapa_valores_limp = [
    ["3.0", "3.0", "3.0", "3.0"],  
    ["2.5", "2.5", "2.5", "2.5"],
    ["2.0", "2.0", "2.0", "2.0"],
    ["1.5", "1.5", "1.5", "1.5"]
]

labels_celulas = []

for col_idx, rpm_txt in enumerate(faixas_rpm):
    tk.Label(frame_mapa, text=f"{rpm_txt}RPM", bg=COR_PAINEL, fg=COR_TEXTO, font=("Courier", 6, "bold")).grid(row=1, column=col_idx+1, padx=4, pady=1)

for row_idx, map_txt in enumerate(faixas_map):
    tk.Label(frame_mapa, text=map_txt, bg=COR_PAINEL, fg=COR_TEXTO, font=("Courier", 6, "bold")).grid(row=row_idx+2, column=0, padx=4, sticky="e")
    linha_labels = []
    for col_idx in range(4):
        lbl = tk.Label(frame_mapa, text="-", bg="#252436", fg=COR_TEXTO, font=("Arial", 7, "bold"), width=7, height=1, relief="groove")
        lbl.grid(row=row_idx+2, column=col_idx+1, padx=2, pady=1)
        linha_labels.append(lbl)
    labels_celulas.append(linha_labels)


def atualizar_celula_ativa_mapa():
    if motor["rpm"] <= 1500: c = 0
    elif motor["rpm"] <= 3200: c = 1
    elif motor["rpm"] <= 4800: c = 2
    else: c = 3
    
    if motor["map"] <= 0.6: r = 3
    elif motor["map"] <= 1.0: r = 2
    elif motor["map"] <= 1.5: r = 1
    else: r = 0

    rede_com_falha = (motor["bcm_status"] == "OFFLINE" or motor["tcm_status"] == "OFFLINE")
    tabela_ativa = mapa_valores_limp if rede_com_falha else mapa_valores_normal

    for row in range(4):
        for col in range(4):
            val_txt = tabela_ativa[row][col]
            if row == r and col == c and motor["ignicao"] == "ON":
                labels_celulas[row][col].config(text=f"{val_txt}ms", bg=COR_AZUL, fg="#000")
            else:
                labels_celulas[row][col].config(text=f"{val_txt}ms", bg="#252436", fg=COR_TEXTO if not rede_com_falha else COR_LARANJA)


def piscar_led(modulo, cor, duracao_ms=60):
    canvas = leds_rede.get(modulo)
    if not canvas or motor.get(f"{modulo}_status") != "ONLINE":
        return
    canvas.itemconfig("lamp", fill=cor)
    root.after(duracao_ms, lambda c=canvas: c.itemconfig("lamp", fill=COR_LED_OFF))


def rotear_led_por_msg(msg):
    mapa = (("BCM", "bcm", COR_VERDE), ("CLUSTER", "cluster", COR_VERDE), ("TCM", "tcm", COR_AZUL), ("DIAG", "bcm", COR_LARANJA), ("OBD", "bcm", COR_LARANJA))
    for token, modulo, cor in mapa:
        if token in msg:
            piscar_led(modulo, cor)


def log_sniffer(msg):
    if threading.current_thread() is not threading.main_thread():
        ui_call(log_sniffer, msg)
        return
    
    msg_traduzida = msg
    
    if "0x7DF REQUEST: 01 0C 05" in msg:
        msg_traduzida = f" SCANNER (0x7DF) ➔ Solicitando leitura de Rotação (RPM) e Temperatura do Motor."
    elif "0x7E8 RESPONSE:" in msg:
        msg_traduzida = f" ECM INJEÇÃO (0x7E8) ➔ Retornando dados ao Scanner: Bomba={motor['bomba']} | MAP={motor['map']}bar | Temp={motor['temp_agua']}°C"
    elif "0x200 BROADCAST: IGNITION/AUTH STATUS" in msg:
        msg_traduzida = f" IMOBILIZADOR BCM (0x200) ➔ Status da Ignição Chave: {motor['ignicao']} | Autenticação CAN OK"
    elif "0x101 BROADCAST:" in msg:
        msg_traduzida = f" PAINEL CLUSTER (0x101) ➔ Atualizando mostradores de bordo: {motor['rpm']} RPM | {motor['temp_agua']}°C"
    elif "0x350 BROADCAST:" in msg:
        msg_traduzida = f" TRANSMISSÃO TCM (0x350) ➔ Monitoramento de Câmbio Ativo: Marcha Atual = {motor['marcha']}"
    elif "0x150 ALERTA ULTRASSOM" in msg:
        msg_traduzida = f" 🛑 [SAFETY ALERT] OBSTÁCULO DETECTADO EM {motor['distancia_ultra']}CM! CORTANDO TORQUE!"
    elif "0x250 ALERTA BATERIA" in msg:
        msg_traduzida = f" 🛑 [BATTERY CRITICAL] TENSÃO DE ALIMENTAÇÃO ABAIXO DO LIMITE: {motor['tensao_bateria']}V! SISTEMA BLOQUEADO."
    elif "[IN]" in msg and "SINAL APP SENSOR" in msg:
        msg_traduzida = f"📥 ENTRADA SERIAL ➔ Pedal APP processado em Decimal: {motor['pedal_app']}%"
    elif "[OUT]" in msg and "TRANSMISSÃO RPM" in msg:
        msg_traduzida = f"📤 SAÍDA SERIAL ➔ Transmitindo frequência de Rotação: {motor['rpm']} RPM"
    elif "[OUT]" in msg and "ATUAÇÃO BORBOLETA TBI" in msg:
        msg_traduzida = f"📤 SAÍDA SERIAL ➔ Enviando pulso PWM para Corpo de Borboleta: {motor['borboleta_tbi']}% de Abertura"
        
    lista_sniffer.insert(tk.END, msg_traduzida)
    if lista_sniffer.size() > 10:
        lista_sniffer.delete(0)
    lista_sniffer.yview(tk.END)
    rotear_led_por_msg(msg)


def atualizar_valores_virtuais_sensores():
    motor["distancia_ultra"] = int(scale_ultra.get())
    motor["tensao_bateria"] = float(scale_bat.get())
    atualizar_calculos_motor(motor["pedal_app"])


def alternar_pane_rede(modulo):
    chave = f"{modulo}_status"
    novo = "OFFLINE" if motor[chave] == "ONLINE" else "ONLINE"
    motor[chave] = novo
    btns_pane[modulo].config(text=novo, bg=COR_VERDE if novo == "ONLINE" else COR_VERMELHO, fg="#000" if novo == "ONLINE" else "#fff")
    leds_rede[modulo].itemconfig("lamp", fill=COR_LED_OFF)
    if novo == "OFFLINE":
        log_sniffer(f"[TIMEOUT ERROR] {modulo.upper()} DESCONECTADO DO BARRAMENTO CAN")
    else:
        log_sniffer(f"[CAN] {modulo.upper()} ONLINE - NÓ REINTEGRADO AO BARRAMENTO")


def alternar_modo_virtual():
    motor["simulacao_ativa"] = not motor["simulacao_ativa"]
    motor["modo"] = "VIRTUAL" if motor["simulacao_ativa"] else "REAL"
    btn_modo_virtual.config(text=f"MODO {motor['modo']}", bg=COR_VERDE if motor["simulacao_ativa"] else COR_AZUL)
    lbl_modo.config(text=f"MODO: {motor['modo']}", fg=COR_VERDE if motor["simulacao_ativa"] else COR_TEXTO)
    log_sniffer(f"[MODE] ECM OPERANDO EM MODO {motor['modo']}")
    if motor["simulacao_ativa"]:
        threading.Thread(target=loop_simulacao_rede_virtual, daemon=True).start()


btn_modo_virtual.config(command=alternar_modo_virtual)


def aplicar_falhas_no_powertrain(pedal):
    # Condição de Falha Extra 1: Bloqueio por Bateria Baixa (< 11V)
    if motor["tensao_bateria"] < 11.0:
        if int(time.time()) % 4 == 0 and motor["ignicao"] == "ON":
            log_sniffer("0x250 ALERTA BATERIA")
        motor["bomba"] = "OFF"
        return 0, 1.0

    # Condição de Falha Extra 2: Corte por Proximidade Crítica (Ultrassom < 30 cm)
    if motor["distancia_ultra"] < 30:
        if int(time.time()) % 4 == 0 and motor["ignicao"] == "ON":
            log_sniffer("0x150 ALERTA ULTRASSOM")
        motor["bomba"] = "OFF"
        return 0, 0.4

    rpm = 900 + int(pedal * 51)
    map_bar = 0.4 + (pedal * 0.016)
    
    if map_bar >= 1.8:
        motor["bomba"] = "OFF"
        rpm = 900 
        log_sniffer("[ECM ACTUATOR] OVERPRESSURE DETECTED! CUTTING FUEL PUMP FOR ENGINE PROTECTION")
    elif motor["ignicao"] == "ON":
        motor["bomba"] = "ON"

    if motor["bcm_status"] == "OFFLINE":
        rpm = min(rpm, 2000)
    if motor["tcm_status"] == "OFFLINE":
        rpm = int(rpm * 0.6)
        map_bar *= 0.6

    if motor["ignicao"] == "ON":
        if motor["temp_agua"] >= 103:
            rpm = 900
            map_bar = 0.4
            motor["temp_agua"] -= 1  
        else:
            temp_alvo = 85 + int(pedal * 0.18)  
            if motor["temp_agua"] < temp_alvo:
                motor["temp_agua"] += 1
            elif motor["temp_agua"] > temp_alvo:
                motor["temp_agua"] -= 1
                
            if motor["temp_agua"] >= 103:
                log_sniffer("[ECM PROTECTION] EMERGENCY THERMAL OVERHEAT CRITICAL! DROPPING TO 900 RPM")
                rpm = 900
                map_bar = 0.4

    return rpm, round(map_bar, 2)


def atualizar_calculos_motor(valor_pedal):
    if motor["ignicao"] == "OFF":
        motor["pedal_app"] = 0
        motor["borboleta_tbi"] = 0
        if int(float(valor_pedal)) != 0:
            scale_pedal.set(0)
        return
    pedal = int(float(valor_pedal))
    motor["pedal_app"] = pedal
    motor["borboleta_tbi"] = pedal
    motor["rpm"], motor["map"] = aplicar_falhas_no_powertrain(pedal)
    
    start, end = config_atual["start_byte"], config_atual["end_byte"]
    if motor["tensao_bateria"] >= 11.0 and motor["distancia_ultra"] >= 30:
        log_sniffer(f"[IN] {start} {config_atual['id_pedal']} PAYLOAD: {hex(pedal)} {end} -> SINAL APP SENSOR: {pedal}%")
        log_sniffer(f"[OUT] {start} {config_atual['id_rpm']} PAYLOAD: {hex(motor['rpm'])} {end} -> TRANSMISSÃO RPM: {motor['rpm']}")


def alternar_ignicao():
    if motor["tensao_bateria"] < 11.0:
        log_sniffer("0x250 ALERTA BATERIA")
        return
    if motor["bcm_status"] == "OFFLINE" and motor["ignicao"] == "OFF":
        log_sniffer("[BCM_ERROR] ANTITHEFT ACTIVE - PARTIDA BLOCK")
        return
    if motor["ignicao"] == "OFF":
        motor.update({"ignicao": "ON", "bomba": "ON", "temp_agua": 85, "rpm": 900, "map": 0.4})
        btn_ignicao.config(bg=COR_VERDE, text="MOTOR LIGADO", fg="#000")
    else:
        motor.update({"ignicao": "OFF", "bomba": "OFF", "rpm": 0, "map": 1.0, "temp_agua": 25, "pedal_app": 0, "borboleta_tbi": 0, "marcha": "D1"})
        scale_pedal.set(0)
        btn_ignicao.config(bg=COR_VERMELHO, text="IGNIÇÃO (CHAVE)", fg="#fff")


def processar_tcm():
    if motor["tcm_status"] == "OFFLINE":
        motor["marcha"] = "LIMP"
        return
    marcha_antiga = motor["marcha"]
    motor["marcha"] = "D2" if motor["rpm"] >= 3200 else "D1"
    if marcha_antiga != motor["marcha"]:
        piscar_led("tcm", COR_AZUL, 1000)


frame_tempo_roda = 0

def atualizar_interface():
    global frame_tempo_roda
    while True:
        try:
            func, args, kwargs = fila_ui.get_nowait()
            func(*args, **kwargs)
        except queue.Empty:
            break

    blink = int(time.time() * 4) % 2 == 0
    processar_tcm()
    if motor["ignicao"] == "ON":
        motor["rpm"], motor["map"] = aplicar_falhas_no_powertrain(motor["pedal_app"])
        frame_tempo_roda += 1 

    atualizar_celula_ativa_mapa()
    size = int(64 * S)
    
    for idx, key in enumerate(["pedal", "map", "bomba", "modulo", "temp", "borboleta"]):
        asset_data, is_gif = assets_originais[key]
        if is_gif:
            total_frames = len(asset_data)
            if key == "pedal":
                frame_idx = int((motor["pedal_app"] / 100) * (total_frames - 1))
                frame_idx = max(0, min(frame_idx, total_frames - 1))
                base_img = asset_data[frame_idx]
            elif key == "borboleta":
                frame_idx = int(((motor["borboleta_tbi"] * 0.5) / 100) * (total_frames - 1))
                frame_idx = max(0, min(frame_idx, total_frames - 1))
                base_img = asset_data[frame_idx]
            elif key == "temp":
                proporcao_temp = max(0.0, min(1.0, (motor["temp_agua"] - 25) / 78))
                frame_idx = int((1.0 - proporcao_temp) * (total_frames - 1))
                frame_idx = max(0, min(frame_idx, total_frames - 1))
                base_img = asset_data[frame_idx]
            else:
                if (key == "bomba" and motor["bomba"] == "ON") or (key != "bomba" and motor["ignicao"] == "ON"):
                    base_img = asset_data[frame_tempo_roda % total_frames]
                else:
                    base_img = asset_data[0] 
        else:
            base_img = asset_data 

        imagem_redimensionada = base_img.resize((size, size), Image.Resampling.NEAREST)
        cache_tk[f"{key}_tk"] = ImageTk.PhotoImage(imagem_redimensionada)
        lbls_imagens[idx].config(image=cache_tk[f"{key}_tk"])

    cor_app = COR_VERDE if motor["pedal_app"] < 40 else "#f7d51d" if motor["pedal_app"] < 80 else COR_VERMELHO
    
    # Atualização da Coluna 1 combinada (MAP + Ultrassom + Bateria)
    cor_bat = COR_VERDE if motor["tensao_bateria"] >= 11.5 else COR_VERMELHO
    cor_ultra = COR_VERDE if motor["distancia_ultra"] >= 40 else COR_VERMELHO
    lbls_valores[1].config(
        text=f"PRESSÃO MAP: {motor['map']} bar\n"
             f"ULTRASSOM: {motor['distancia_ultra']} cm\n"
             f"BATERIA SENS: {motor['tensao_bateria']} V", 
        fg=COR_TEXTO
    )

    lbls_valores[0].config(text=f"SINAL APP: {motor['pedal_app']}%", fg=cor_app)
    lbls_valores[2].config(text=f"STATUS: {motor['bomba']}\nTENSÃO: {12.6 if motor['bomba']=='ON' else 0.0:.1f}V", fg=COR_VERDE if motor["bomba"] == "ON" else COR_VERMELHO)
    lbls_valores[3].config(text=f"BOMBA: {motor['bomba']} | MOT: {motor['ignicao']}", fg=COR_TEXTO)
    lbls_valores[4].config(text=f"CLUSTER RPM: {motor['rpm']}\nTEMP. FLUIDO: {motor['temp_agua']}°C", fg=COR_TEXTO)
    lbls_valores[5].config(text=f"ABERTURA TBI: {motor['borboleta_tbi']}%\nTCM: {motor['tcm_status']}", fg=COR_TEXTO)

    if motor["distancia_ultra"] < 30:
        lbl_rpm_top.config(text="🛑 ALERTA DE COLISÃO - EMBARGO ULTRASSOM 🛑", fg=COR_VERMELHO if blink else COR_LARANJA)
    elif motor["tensao_bateria"] < 11.0:
        lbl_rpm_top.config(text="🛑 FALHA ELÉTRICA: SUBTENSAO BATERIA 🛑", fg=COR_VERMELHO if blink else COR_LARANJA)
    elif motor["temp_agua"] >= 102:
        lbl_rpm_top.config(text=f"🛑 PROTEÇÃO TÉRMICA ATIVA: {motor['rpm']} RPM 🛑", fg=COR_VERMELHO if blink else COR_LARANJA)
    else:
        lbl_rpm_top.config(text=f"ROTAÇÃO: {motor['rpm']} RPM", fg=COR_VERDE)

    lbl_marcha.config(text=f"MARCHA: {motor['marcha']}", fg=COR_AZUL)
    root.after(100, atualizar_interface)


def loop_simulacao_rede_virtual():
    while motor["simulacao_ativa"]:
        if motor["bcm_status"] == "ONLINE": log_sniffer("[BCM RX] 0x200 BROADCAST: IGNITION/AUTH STATUS")
        if motor["tcm_status"] == "ONLINE": log_sniffer(f"[TCM RX] 0x350 BROADCAST: GEAR={motor['marcha']}")
        log_sniffer("[DIAG OBD-II] 0x7DF REQUEST: 01 0C 05")
        log_sniffer(f"[ECM DIAG] 0x7E8 RESPONSE: PUMP_STATUS={motor['bomba']} MAP={motor['map']} TEMP={motor['temp_agua']}")
        time.sleep(1.0)


# Abas secundárias mantidas
tk.Label(aba_config, text="PAINEL DE CONFIGURAÇÃO DE IDs DA REDE CAN (TAB para alternar)", bg=COR_PAINEL, fg=COR_LARANJA, font=("Arial", 10, "bold")).place(relx=0.5, rely=0.1, anchor="center")
campos_cfg = {}
labels_ids = [("start_byte", "Start:"), ("end_byte", "End:"), ("id_pedal", "Id Pedal:"), ("id_rpm", "Id RPM:"), ("id_map", "Id MAP:"), ("id_temp", "Id Temp:"), ("id_tbi", "Id TBI:")]
for i, (chave, texto) in enumerate(labels_ids):
    col, row = i % 3, i // 3
    tk.Label(aba_config, text=texto, bg=COR_PAINEL, fg=COR_TEXTO).place(relx=0.1 + (col * 0.3), rely=0.3 + (row * 0.15))
    ent = tk.Entry(aba_config, width=8)
    ent.insert(0, config_atual.get(chave, "0x00"))
    ent.place(relx=0.22 + (col * 0.3), rely=0.3 + (row * 0.15))
    campos_cfg[chave] = ent


def salvar_matriz():
    for chave, ent in campos_cfg.items(): config_atual[chave] = ent.get().strip().lower()
    salvar_config(config_atual)


btn_salvar = tk.Button(aba_config, text="SALVAR CONFIG", bg=COR_LARANJA, fg=COR_FUNDO, font=("Arial", 10, "bold"), command=salvar_matriz)
btn_salvar.place(relx=0.5, rely=0.8, anchor="center")

tk.Label(aba_usb, text="CONEXÃO SERIAL HARDWARE (TJA1050 / ARDUINO / ESP32)", bg=COR_PAINEL, fg=COR_LARANJA, font=("Arial", 10, "bold")).place(relx=0.5, rely=0.1, anchor="center")
combo_portas = ttk.Combobox(aba_usb, width=30, state="readonly")
combo_portas.place(relx=0.5, rely=0.35, anchor="center")


def atualizar_portas():
    combo_portas["values"] = [p.device for p in serial.tools.list_ports.comports()]
    if combo_portas["values"]: combo_portas.current(0)


tk.Button(aba_usb, text="⟳ ATUALIZAR PORTAS", bg="#ffffff", command=atualizar_portas).place(relx=0.5, rely=0.55, anchor="center")
thread_rodando = False
ser = None

atualizar_portas()
aba_dash.tkraise()
atualizar_interface()
root.mainloop()