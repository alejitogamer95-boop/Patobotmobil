import os
import re
import time
import json
import threading
import queue
import asyncio
import io
import unicodedata
import urllib.request
import urllib.error
from collections import deque, defaultdict
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, font
import pygame
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, GiftEvent, FollowEvent, LikeEvent
import edge_tts
import psutil
import yt_dlp

CONFIG_FILE = "config.json"
CONFIG_DEFAULTS = {
    "usuario": "@frann.aguirre", "volumen": 0.5, "volumen_alertas": 0.8, "volumen_musica": 0.4,
    "voz": "es-MX-JorgeNeural", "velocidad": "+30%", "tono": "+0Hz", "limite_caracteres": 100,
    "palabras_censuradas": "groseria1, groseria2", "reemplazos": "gg:buena partida, xq:porque",
    "restringir_subs": False, "nivel_sub_minimo": 2, "restringir_mods": False, "restringir_lista": False,
    "lista_blanca": "amigo1, amigo2", "alerta_regalos": True, "alerta_follows": True,
    "alerta_likes_general": True, "meta_likes_general": 100, "repetir_likes_general": True,
    "alerta_likes_persona": True, "meta_likes_persona": 50, "repetir_likes_persona": True,
    "url_regalo": "https://www.myinstants.com/media/sounds/coin.mp3",
    "url_follow": "https://www.myinstants.com/media/sounds/discord-notification.mp3",
    "url_like_general": "https://www.myinstants.com/media/sounds/pop-sound.mp3",
    "url_like_persona": "https://www.myinstants.com/media/sounds/coin.mp3",
    "cmd_play": "!play, !p", "cmd_skip": "!skip", "cmd_stop": "!stop, !parar",
    "cmd_pause": "!pause", "cmd_resume": "!resume", "cmd_volume": "!volume, !vol",
    "cmd_song": "!song, !cancion", "fuente_interfaz": "sans-serif"
}

def cargar_configuracion():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**CONFIG_DEFAULTS, **json.load(f)}
        except Exception:
            return CONFIG_DEFAULTS
    return CONFIG_DEFAULTS

def guardar_configuracion(datos):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error guardando config: {e}")

config = cargar_configuracion()
VOLUMEN = config["volumen"]
VOLUMEN_ALERTAS = config.get("volumen_alertas", 0.8)
VOLUMEN_MUSICA = config.get("volumen_musica", 0.4)
VELOCIDAD_AUDIO = config["velocidad"]
VOZ_TTS = config["voz"]
TONO_TTS = config.get("tono", "+0Hz")
HISTORIAL_RECIENTE = deque(maxlen=20)
TIEMPO_INICIO = time.time()
CONTADOR_LIKES_GENERAL = 0
LIKES_POR_USUARIO = defaultdict(int)

STATS = {"comentarios": 0, "regalos": 0, "follows": 0, "likes_totales": 0}

pygame.mixer.init()
pygame.mixer.set_num_channels(16)

cola_mensajes = queue.Queue(maxsize=50)
cola_musica = deque()
cancion_actual = None

def reproducir_sonido_url(url):
    url = url.strip()
    if not url or not url.startswith("http"): return
    def _stream():
        try:
            target_url = url
            if "myinstants.com" in target_url and not target_url.endswith(".mp3"):
                slug = target_url.rstrip("/").split("/")[-1]
                target_url = f"https://www.myinstants.com/media/sounds/{slug}.mp3"
            req = urllib.request.Request(target_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
            if data:
                sonido = pygame.mixer.Sound(io.BytesIO(data))
                canal = pygame.mixer.find_channel(True)
                if canal:
                    canal.set_volume(float(gui.slider_volumen_alertas.get()))
                    canal.play(sonido)
        except Exception as e:
            gui.agregar_log(f"[Audio URL Error]: {e}")
    threading.Thread(target=_stream, daemon=True).start()

def limpiar_busqueda(query):
    query = re.sub(r'[^\w\s]', ' ', query.lower())
    palabras = [p for p in query.split() if p not in {'video', 'oficial', 'official', 'lyric', 'audio'}]
    return " ".join(palabras) if palabras else query

def obtener_stream_audio(busqueda):
    motores = [busqueda] if busqueda.startswith("http") else [
        f"scsearch1:{limpiar_busqueda(busqueda)}",
        f"ytsearch1:{limpiar_busqueda(busqueda)}"
    ]
    ydl_opts = {'format': 'bestaudio[protocol^=http]/bestaudio', 'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for m in motores:
            try:
                info = ydl.extract_info(m, download=False)
                if info and 'entries' in info and info['entries']: info = info['entries'][0]
                if info and info.get('duration', 0) <= 600:
                    url = info.get('url')
                    titulo = info.get('title', 'Canción')
                    return url, titulo
            except Exception: continue
    return None, None

def reproductor_musica_loop():
    global cancion_actual
    archivo_temp = "temp_music.mp3"
    while True:
        if cola_musica and not pygame.mixer.music.get_busy() and not getattr(gui, 'musica_pausada', False):
            query, usuario = cola_musica.popleft()
            gui.actualizar_lista_musica_ui()
            gui.agregar_log(f"[MÚSQUEDA] Buscando: {query}...")
            stream_url, titulo = obtener_stream_audio(query)
            if stream_url:
                try:
                    cancion_actual = f"{titulo} (por @{usuario})"
                    gui.actualizar_cancion_actual_ui(cancion_actual)
                    pygame.mixer.music.stop()
                    pygame.mixer.music.unload()
                    req = urllib.request.Request(stream_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=15) as resp, open(archivo_temp, 'wb') as f:
                        f.write(resp.read())
                    if os.path.exists(archivo_temp):
                        pygame.mixer.music.load(archivo_temp)
                        pygame.mixer.music.set_volume(float(gui.slider_volumen_musica.get()))
                        pygame.mixer.music.play()
                        while pygame.mixer.music.get_busy() or getattr(gui, 'musica_pausada', False):
                            time.sleep(1)
                except Exception as e: gui.agregar_log(f"[Error Música]: {e}")
                finally:
                    cancion_actual = None
                    gui.actualizar_cancion_actual_ui("Ninguna")
        time.sleep(1)

threading.Thread(target=reproductor_musica_loop, daemon=True).start()
class ScrollableFrame(ttk.Frame):
    """Marco deslizable optimizado para pantallas táctiles estrechas."""
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, bg="#1e1e2e", highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_window = ttk.Frame(self.canvas)

        self.window_id = self.canvas.create_window((0, 0), window=self.scrollable_window, anchor="nw")
        
        # Fuerza a que el contenido tome el 100% del ancho visible de la pantalla
        self.scrollable_window.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._al_cambiar_tamanio_canvas)

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

    def _al_cambiar_tamanio_canvas(self, event):
        self.canvas.itemconfig(self.window_id, width=event.width)

class PanelControl:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TikTok Bot - Móvil")
        self.root.geometry("380x720")
        self.root.configure(bg="#1e1e2e")
        self.root.protocol("WM_DELETE_WINDOW", self.al_cerrar)

        self.proceso_actual = psutil.Process(os.getpid())
        self.tiempo_conexion_inicio = None
        self.audio_pausado = False
        self.musica_pausada = False
        
        self.restringir_subs = tk.BooleanVar(value=config["restringir_subs"])
        self.restringir_mods = tk.BooleanVar(value=config["restringir_mods"])
        self.restringir_lista = tk.BooleanVar(value=config["restringir_lista"])
        self.alerta_regalos = tk.BooleanVar(value=config.get("alerta_regalos", True))
        self.alerta_follows = tk.BooleanVar(value=config.get("alerta_follows", True))
        self.alerta_likes_general = tk.BooleanVar(value=config.get("alerta_likes_general", True))
        self.repetir_likes_general = tk.BooleanVar(value=config.get("repetir_likes_general", True))
        self.alerta_likes_persona = tk.BooleanVar(value=config.get("alerta_likes_persona", True))
        self.repetir_likes_persona = tk.BooleanVar(value=config.get("repetir_likes_persona", True))

        self.client_tiktok = None
        self.conectado = False
        self.fuente_actual = config.get("fuente_interfaz", "sans-serif")

        style = ttk.Style()
        style.theme_use('default')
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabelframe", background="#1e1e2e", foreground="#cdd6f4")
        style.configure("TLabelframe.Label", background="#1e1e2e", foreground="#cdd6f4", font=(self.fuente_actual, 10, "bold"))
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4", font=(self.fuente_actual, 10))
        style.configure("TCheckbutton", background="#1e1e2e", foreground="#cdd6f4", font=(self.fuente_actual, 10))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=2, pady=2)

        self.tab_principal = ScrollableFrame(self.notebook)
        self.tab_musica = ScrollableFrame(self.notebook)
        self.tab_tts = ScrollableFrame(self.notebook)
        self.tab_filtros = ScrollableFrame(self.notebook)
        self.tab_alertas = ScrollableFrame(self.notebook)

        self.notebook.add(self.tab_principal, text=" Dashboard ")
        self.notebook.add(self.tab_musica, text=" Música ")
        self.notebook.add(self.tab_tts, text=" Voz ")
        self.notebook.add(self.tab_filtros, text=" Filtros ")
        self.notebook.add(self.tab_alertas, text=" Alertas ")

        # --- DASHBOARD ---
        win_dash = self.tab_principal.scrollable_window
        f_conn = ttk.LabelFrame(win_dash, text=" Conexión Live ")
        f_conn.pack(fill="x", padx=4, pady=4)
        ttk.Label(f_conn, text="Usuario:").pack(anchor="w", padx=4)
        self.entry_user = tk.Entry(f_conn, bg="#11111b", fg="#cdd6f4", insertbackground="white", font=(self.fuente_actual, 11), relief="flat")
        self.entry_user.insert(0, config["usuario"])
        self.entry_user.pack(fill="x", padx=4, pady=4)
        self.btn_conectar = tk.Button(f_conn, text="Conectar Live", bg="#a6e3a1", fg="#11111b", relief="flat", command=self.alternar_conexion, font=(self.fuente_actual, 10, "bold"), pady=4)
        self.btn_conectar.pack(fill="x", padx=4, pady=4)

        f_estado = ttk.Frame(win_dash)
        f_estado.pack(fill="x", padx=4, pady=2)
        self.lbl_estado = tk.Label(f_estado, text="Estado: Desconectado", fg="#f38ba8", bg="#1e1e2e", font=(self.fuente_actual, 10, "bold"))
        self.lbl_estado.pack(anchor="w")
        self.lbl_ram = ttk.Label(f_estado, text="RAM: 0.0 MB")
        self.lbl_ram.pack(side="left")
        self.lbl_cola = ttk.Label(f_estado, text="En cola: 0/50")
        self.lbl_cola.pack(side="right")
        self.lbl_tiempo_live = tk.Label(win_dash, text="Live activo: 00:00:00", fg="#89b4fa", bg="#1e1e2e", font=(self.fuente_actual, 10, "bold"))
        self.lbl_tiempo_live.pack(anchor="w", padx=4, pady=2)

        f_stats = ttk.LabelFrame(win_dash, text=" Estadísticas ")
        f_stats.pack(fill="x", padx=4, pady=4)
        self.lbl_stat_chat = ttk.Label(f_stats, text="Leídos: 0")
        self.lbl_stat_chat.grid(row=0, column=0, padx=4, pady=2, sticky="w")
        self.lbl_stat_gifts = ttk.Label(f_stats, text="Regalos: 0")
        self.lbl_stat_gifts.grid(row=0, column=1, padx=4, pady=2, sticky="w")
        self.lbl_stat_follows = ttk.Label(f_stats, text="Follows: 0")
        self.lbl_stat_follows.grid(row=1, column=0, padx=4, pady=2, sticky="w")
        self.lbl_stat_likes = ttk.Label(f_stats, text="Likes: 0")
        self.lbl_stat_likes.grid(row=1, column=1, padx=4, pady=2, sticky="w")

        f_ctrl = ttk.LabelFrame(win_dash, text=" Control de Música ")
        f_ctrl.pack(fill="x", padx=4, pady=4)
        f_ctrl.columnconfigure(0, weight=1)
        f_ctrl.columnconfigure(1, weight=1)
        self.btn_pause_musica = tk.Button(f_ctrl, text="Pausar / Reanudar", bg="#f9e2af", fg="#11111b", relief="flat", command=self.alternar_pausa_musica, font=(self.fuente_actual, 9, "bold"), pady=4)
        self.btn_pause_musica.grid(row=0, column=0, sticky="ew", padx=2, pady=4)
        btn_next_musica = tk.Button(f_ctrl, text="Siguiente ⏭", bg="#89b4fa", fg="#11111b", relief="flat", command=self.saltar_cancion_manual, font=(self.fuente_actual, 9, "bold"), pady=4)
        btn_next_musica.grid(row=0, column=1, sticky="ew", padx=2, pady=4)

        f_log = ttk.LabelFrame(win_dash, text=" Registro ")
        f_log.pack(fill="x", padx=4, pady=4)
        self.log_box = scrolledtext.ScrolledText(f_log, height=6, bg="#11111b", fg="#a6e3a1", insertbackground="white", font=(self.fuente_actual, 9), relief="flat")
        self.log_box.pack(padx=2, pady=2, fill="x")

        # --- TAB MÚSICA ---
        win_mus = self.tab_musica.scrollable_window
        f_rep = ttk.LabelFrame(win_mus, text=" Reproducción ")
        f_rep.pack(fill="x", padx=4, pady=4)
        self.lbl_now_playing = tk.Label(f_rep, text="Sonando: Ninguna", fg="#a6e3a1", bg="#1e1e2e", font=(self.fuente_actual, 9, "bold"), anchor="w", wraplength=320)
        self.lbl_now_playing.pack(fill="x", padx=4, pady=4)

        ttk.Label(win_mus, text="Volumen Música:").pack(anchor="w", padx=4)
        self.slider_volumen_musica = ttk.Scale(win_mus, from_=0.0, to=1.0, value=VOLUMEN_MUSICA, command=self.cambiar_volumen_musica)
        self.slider_volumen_musica.pack(fill="x", padx=4, pady=4)

        f_lista = ttk.LabelFrame(win_mus, text=" Lista de Espera ")
        f_lista.pack(fill="x", padx=4, pady=4)
        self.listbox_musica = tk.Listbox(f_lista, height=5, bg="#11111b", fg="#cdd6f4", font=(self.fuente_actual, 9), relief="flat")
        self.listbox_musica.pack(fill="x", padx=4, pady=4)

        f_cmd_cfg = ttk.LabelFrame(win_mus, text=" Comandos del Chat ")
        f_cmd_cfg.pack(fill="x", padx=4, pady=4)
        def _add_cmd_entry(lbl, key):
            ttk.Label(f_cmd_cfg, text=lbl).pack(anchor="w", padx=4)
            e = tk.Entry(f_cmd_cfg, bg="#11111b", fg="#cdd6f4", font=(self.fuente_actual, 9), relief="flat")
            e.insert(0, config.get(key, ""))
            e.pack(fill="x", padx=4, pady=2)
            return e
        self.entry_cmd_play = _add_cmd_entry("Play:", "cmd_play")
        self.entry_cmd_skip = _add_cmd_entry("Skip:", "cmd_skip")
        self.entry_cmd_stop = _add_cmd_entry("Stop:", "cmd_stop")
        self.entry_cmd_pause = _add_cmd_entry("Pause:", "cmd_pause")
        self.entry_cmd_resume = _add_cmd_entry("Resume:", "cmd_resume")
        self.entry_cmd_vol = _add_cmd_entry("Volumen:", "cmd_volume")
        self.entry_cmd_song = _add_cmd_entry("Canción Actual:", "cmd_song")

        # --- TAB VOZ ---
        win_tts = self.tab_tts.scrollable_window
        f_tts_cfg = ttk.LabelFrame(win_tts, text=" Parámetros TTS ")
        f_tts_cfg.pack(fill="x", padx=4, pady=4)
        ttk.Label(f_tts_cfg, text="Volumen TTS:").pack(anchor="w", padx=4)
        self.slider_volumen = ttk.Scale(f_tts_cfg, from_=0.0, to=1.0, value=VOLUMEN)
        self.slider_volumen.pack(fill="x", padx=4, pady=4)
        ttk.Label(f_tts_cfg, text="Voz:").pack(anchor="w", padx=4)
        self.combo_voz = ttk.Combobox(f_tts_cfg, values=["es-MX-JorgeNeural", "es-MX-DaliaNeural", "es-ES-ElviraNeural", "es-AR-TomasNeural"], state="readonly")
        self.combo_voz.set(VOZ_TTS)
        self.combo_voz.pack(fill="x", padx=4, pady=4)
        ttk.Label(f_tts_cfg, text="Velocidad:").pack(anchor="w", padx=4)
        self.combo_vel = ttk.Combobox(f_tts_cfg, values=["+0%", "+15%", "+30%", "+45%", "+60%"], state="readonly")
        self.combo_vel.set(VELOCIDAD_AUDIO)
        self.combo_vel.pack(fill="x", padx=4, pady=4)
        ttk.Label(f_tts_cfg, text="Tono:").pack(anchor="w", padx=4)
        self.combo_tono = ttk.Combobox(f_tts_cfg, values=["-10Hz", "-5Hz", "+0Hz", "+5Hz", "+10Hz"], state="readonly")
        self.combo_tono.set(TONO_TTS)
        self.combo_tono.pack(fill="x", padx=4, pady=4)
        ttk.Label(f_tts_cfg, text="Límite Caracteres:").pack(anchor="w", padx=4)
        self.entry_limite = tk.Entry(f_tts_cfg, bg="#11111b", fg="#cdd6f4", font=(self.fuente_actual, 10), relief="flat")
        self.entry_limite.insert(0, str(config.get("limite_caracteres", 100)))
        self.entry_limite.pack(fill="x", padx=4, pady=4)
        self.btn_pausa = tk.Button(win_tts, text="Pausar TTS", bg="#f9e2af", fg="#11111b", relief="flat", command=self.conmutar_pausa, font=(self.fuente_actual, 9, "bold"), pady=4)
        self.btn_pausa.pack(fill="x", padx=4, pady=4)
        # --- TAB FILTROS ---
        win_fil = self.tab_filtros.scrollable_window
        f_font = ttk.LabelFrame(win_fil, text=" Fuente GUI ")
        f_font.pack(fill="x", padx=4, pady=4)
        self.combo_fuente = ttk.Combobox(f_font, values=sorted(font.families()), state="readonly")
        self.combo_fuente.set(self.fuente_actual)
        self.combo_fuente.pack(fill="x", padx=4, pady=4)
        btn_apply_f = tk.Button(f_font, text="Aplicar Fuente", bg="#89b4fa", fg="#11111b", relief="flat", command=self.aplicar_nueva_fuente, pady=4)
        btn_apply_f.pack(fill="x", padx=4, pady=4)

        f_rest = ttk.LabelFrame(win_fil, text=" Restricciones ")
        f_rest.pack(fill="x", padx=4, pady=4)
        ttk.Checkbutton(f_rest, text="Solo Subs", variable=self.restringir_subs).pack(anchor="w", padx=4, pady=2)
        f_sub = ttk.Frame(f_rest)
        f_sub.pack(fill="x", padx=4, pady=2)
        ttk.Label(f_sub, text="Nivel Mín Sub:").pack(side="left")
        self.entry_nivel_sub = tk.Entry(f_sub, bg="#11111b", fg="#cdd6f4", width=4, relief="flat")
        self.entry_nivel_sub.insert(0, str(config.get("nivel_sub_minimo", 2)))
        self.entry_nivel_sub.pack(side="left", padx=4)
        ttk.Checkbutton(f_rest, text="Solo Mods", variable=self.restringir_mods).pack(anchor="w", padx=4, pady=2)
        ttk.Checkbutton(f_rest, text="Solo Lista Blanca", variable=self.restringir_lista).pack(anchor="w", padx=4, pady=2)
        ttk.Label(f_rest, text="Lista Blanca (separados por coma):").pack(anchor="w", padx=4, pady=2)
        self.entry_lista = tk.Entry(f_rest, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_lista.insert(0, config.get("lista_blanca", ""))
        self.entry_lista.pack(fill="x", padx=4, pady=4)

        f_cen = ttk.LabelFrame(win_fil, text=" Palabras Prohibidas ")
        f_cen.pack(fill="x", padx=4, pady=4)
        self.entry_censura = tk.Entry(f_cen, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_censura.insert(0, config.get("palabras_censuradas", ""))
        self.entry_censura.pack(fill="x", padx=4, pady=4)

        f_rep = ttk.LabelFrame(win_fil, text=" Diccionario Reemplazos ")
        f_rep.pack(fill="x", padx=4, pady=4)
        self.entry_reemplazos = tk.Entry(f_rep, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_reemplazos.insert(0, config.get("reemplazos", ""))
        self.entry_reemplazos.pack(fill="x", padx=4, pady=4)

        # --- TAB ALERTAS ---
        win_alt = self.tab_alertas.scrollable_window
        f_alt_aud = ttk.LabelFrame(win_alt, text=" Sonidos Alertas ")
        f_alt_aud.pack(fill="x", padx=4, pady=4)
        ttk.Label(f_alt_aud, text="Volumen Alertas:").pack(anchor="w", padx=4)
        self.slider_volumen_alertas = ttk.Scale(f_alt_aud, from_=0.0, to=1.0, value=VOLUMEN_ALERTAS)
        self.slider_volumen_alertas.pack(fill="x", padx=4, pady=4)

        ttk.Checkbutton(f_alt_aud, text="Regalos Audio URL:", variable=self.alerta_regalos).pack(anchor="w", padx=4)
        self.entry_url_regalo = tk.Entry(f_alt_aud, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_url_regalo.insert(0, config.get("url_regalo", ""))
        self.entry_url_regalo.pack(fill="x", padx=4, pady=4)

        ttk.Checkbutton(f_alt_aud, text="Follows Audio URL:", variable=self.alerta_follows).pack(anchor="w", padx=4)
        self.entry_url_follow = tk.Entry(f_alt_aud, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_url_follow.insert(0, config.get("url_follow", ""))
        self.entry_url_follow.pack(fill="x", padx=4, pady=4)

        f_lks_g = ttk.LabelFrame(win_alt, text=" Meta Likes General ")
        f_lks_g.pack(fill="x", padx=4, pady=4)
        ttk.Checkbutton(f_lks_g, text="Activar", variable=self.alerta_likes_general).pack(anchor="w", padx=4)
        self.entry_meta_likes_general = tk.Entry(f_lks_g, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_meta_likes_general.insert(0, str(config.get("meta_likes_general", 100)))
        self.entry_meta_likes_general.pack(fill="x", padx=4, pady=4)
        self.entry_url_like_general = tk.Entry(f_lks_g, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_url_like_general.insert(0, config.get("url_like_general", ""))
        self.entry_url_like_general.pack(fill="x", padx=4, pady=4)

        f_lks_p = ttk.LabelFrame(win_alt, text=" Meta Likes Persona ")
        f_lks_p.pack(fill="x", padx=4, pady=4)
        ttk.Checkbutton(f_lks_p, text="Activar", variable=self.alerta_likes_persona).pack(anchor="w", padx=4)
        self.entry_meta_likes_persona = tk.Entry(f_lks_p, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_meta_likes_persona.insert(0, str(config.get("meta_likes_persona", 50)))
        self.entry_meta_likes_persona.pack(fill="x", padx=4, pady=4)
        self.entry_url_like_persona = tk.Entry(f_lks_p, bg="#11111b", fg="#cdd6f4", relief="flat")
        self.entry_url_like_persona.insert(0, config.get("url_like_persona", ""))
        self.entry_url_like_persona.pack(fill="x", padx=4, pady=4)

        self.actualizar_monitoreo_ram()
        self.actualizar_cronometro_live()

    def aplicar_nueva_fuente(self):
        f = self.combo_fuente.get()
        self.fuente_actual = f
        style = ttk.Style()
        style.configure("TLabelframe.Label", font=(f, 10, "bold"))
        style.configure("TLabel", font=(f, 10))
        self.log_box.config(font=(f, 9))
        self.listbox_musica.config(font=(f, 9))

    def cambiar_volumen_musica(self, val): pygame.mixer.music.set_volume(float(val))
    def alternar_pausa_musica(self):
        if self.musica_pausada:
            pygame.mixer.music.unpause()
            self.musica_pausada = False
        else:
            pygame.mixer.music.pause()
            self.musica_pausada = True

    def saltar_cancion_manual(self):
        self.musica_pausada = False
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()

    def obtener_lista_comandos(self, entry):
        return [c.strip() for c in entry.get().strip().lower().split(",") if c.strip()]

    def actualizar_lista_musica_ui(self):
        def _upd():
            self.listbox_musica.delete(0, tk.END)
            for idx, (q, u) in enumerate(cola_musica, start=1):
                self.listbox_musica.insert(tk.END, f"{idx}. {q} (@{u})")
        self.root.after(0, _upd)

    def actualizar_cancion_actual_ui(self, txt): self.root.after(0, lambda: self.lbl_now_playing.config(text=f"Sonando: {txt}"))
    def obtener_meta_likes_general(self): return int(self.entry_meta_likes_general.get().strip() or 100)
    def obtener_meta_likes_persona(self): return int(self.entry_meta_likes_persona.get().strip() or 50)
    def obtener_nivel_minimo_sub(self): return int(self.entry_nivel_sub.get().strip() or 1)
    def obtener_usuarios_lista_blanca(self): return {u.strip().lower().replace("@", "") for u in self.entry_lista.get().split(",") if u.strip()}
    def obtener_palabras_censuradas(self): return [p.strip().lower() for p in self.entry_censura.get().split(",") if p.strip()]

    def obtener_diccionario_reemplazos(self):
        d = {}
        for item in self.entry_reemplazos.get().split(","):
            if ":" in item:
                k, v = item.split(":", 1)
                d[k.strip().lower()] = v.strip()
        return d

    def actualizar_monitoreo_ram(self):
        try:
            ram_mb = self.proceso_actual.memory_info().rss / (1024 * 1024)
            self.lbl_ram.config(text=f"RAM: {ram_mb:.1f} MB")
        except Exception: pass
        self.root.after(2000, self.actualizar_monitoreo_ram)

    def actualizar_cronometro_live(self):
        if self.conectado and self.tiempo_conexion_inicio:
            t = int(time.time() - self.tiempo_conexion_inicio)
            self.lbl_tiempo_live.config(text=f"Live activo: {t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}")
        else: self.lbl_tiempo_live.config(text="Live activo: 00:00:00")
        self.root.after(1000, self.actualizar_cronometro_live)

    def actualizar_metricas_ui(self):
        self.root.after(0, lambda: self.lbl_stat_chat.config(text=f"Leídos: {STATS['comentarios']}"))
        self.root.after(0, lambda: self.lbl_stat_gifts.config(text=f"Regalos: {STATS['regalos']}"))
        self.root.after(0, lambda: self.lbl_stat_follows.config(text=f"Follows: {STATS['follows']}"))
        self.root.after(0, lambda: self.lbl_stat_likes.config(text=f"Likes: {STATS['likes_totales']}"))

    def conmutar_pausa(self):
        self.audio_pausado = not self.audio_pausado
        self.btn_pausa.config(text="Reanudar TTS" if self.audio_pausado else "Pausar TTS")

    def actualizar_estado(self, txt, col): self.root.after(0, lambda: self.lbl_estado.config(text=f"Estado: {txt}", fg=col))
    def agregar_log(self, msg):
        def _w():
            self.log_box.insert(tk.END, f"{msg}\n")
            self.log_box.see(tk.END)
            self.lbl_cola.config(text=f"En cola: {cola_mensajes.qsize()}/50")
        self.root.after(0, _w)

    def alternar_conexion(self):
        if not self.conectado:
            u = self.entry_user.get().strip()
            if not u: return
            if not u.startswith("@"): u = f"@{u}"
            self.btn_conectar.config(text="Desconectar", bg="#f38ba8")
            threading.Thread(target=iniciar_tiktok, args=(u,), daemon=True).start()
        else:
            self.conectado = False
            if self.client_tiktok:
                try: self.client_tiktok.stop()
                except Exception: pass
            self.btn_conectar.config(text="Conectar Live", bg="#a6e3a1")
            self.actualizar_estado("Desconectado", "#f38ba8")

    def al_cerrar(self):
        guardar_configuracion({
            "usuario": self.entry_user.get().strip(),
            "volumen": float(self.slider_volumen.get()),
            "volumen_alertas": float(self.slider_volumen_alertas.get()),
            "volumen_musica": float(self.slider_volumen_musica.get()),
            "voz": self.combo_voz.get(), "velocidad": self.combo_vel.get(),
            "tono": self.combo_tono.get(), "limite_caracteres": int(self.entry_limite.get() or 100),
            "palabras_censuradas": self.entry_censura.get().strip(),
            "reemplazos": self.entry_reemplazos.get().strip(),
            "restringir_subs": bool(self.restringir_subs.get()),
            "nivel_sub_minimo": self.obtener_nivel_minimo_sub(),
            "restringir_mods": bool(self.restringir_mods.get()),
            "restringir_lista": bool(self.restringir_lista.get()),
            "lista_blanca": self.entry_lista.get().strip(),
            "alerta_regalos": bool(self.alerta_regalos.get()),
            "alerta_follows": bool(self.alerta_follows.get()),
            "alerta_likes_general": bool(self.alerta_likes_general.get()),
            "meta_likes_general": self.obtener_meta_likes_general(),
            "repetir_likes_general": bool(self.repetir_likes_general.get()),
            "alerta_likes_persona": bool(self.alerta_likes_persona.get()),
            "meta_likes_persona": self.obtener_meta_likes_persona(),
            "repetir_likes_persona": bool(self.repetir_likes_persona.get()),
            "url_regalo": self.entry_url_regalo.get().strip(),
            "url_follow": self.entry_url_follow.get().strip(),
            "url_like_general": self.entry_url_like_general.get().strip(),
            "url_like_persona": self.entry_url_like_persona.get().strip(),
            "cmd_play": self.entry_cmd_play.get().strip(), "cmd_skip": self.entry_cmd_skip.get().strip(),
            "cmd_stop": self.entry_cmd_stop.get().strip(), "cmd_pause": self.entry_cmd_pause.get().strip(),
            "cmd_resume": self.entry_cmd_resume.get().strip(), "cmd_volume": self.entry_cmd_vol.get().strip(),
            "cmd_song": self.entry_cmd_song.get().strip(), "fuente_interfaz": self.fuente_actual
        })
        self.root.destroy()

gui = PanelControl()
def extraer_o_limpiar_emojis(texto, max_emojis):
    norm = unicodedata.normalize('NFKD', texto)
    base = "".join([c for c in norm if not unicodedata.combining(c)])
    cnt = 0
    res = []
    for c in base:
        cp = ord(c)
        if (0x1F600 <= cp <= 0x1F64F or 0x1F300 <= cp <= 0x1F5FF or 0x1F680 <= cp <= 0x1F6FF or 
            0x2600 <= cp <= 0x26FF or 0x1F900 <= cp <= 0x1F9FF):
            if cnt < max_emojis:
                res.append(c)
                cnt += 1
        else: res.append(c)
    return re.sub(r'[^\w\s\d@._\-\U00010000-\U0010FFFF]', '', "".join(res)).strip()

def normalizar_texto(t): return extraer_o_limpiar_emojis(t, 0)

def aplicar_diccionario_reemplazos(t, dicc):
    for orig, rep in dicc.items():
        t = re.sub(r'\b' + re.escape(orig) + r'\b', rep, t, flags=re.IGNORECASE)
    return t

async def generar_audio_bytes(texto, voz, vel, tono):
    comm = edge_tts.Communicate(texto, voz, rate=vel, pitch=tono)
    data = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio": data.extend(chunk["data"])
    return io.BytesIO(data)

def procesar_audio():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        txt = cola_mensajes.get()
        try:
            if not gui.audio_pausado:
                buf = loop.run_until_complete(generar_audio_bytes(txt, gui.combo_voz.get(), gui.combo_vel.get(), gui.combo_tono.get()))
                snd = pygame.mixer.Sound(buf)
                ch = pygame.mixer.find_channel(True)
                if ch:
                    ch.set_volume(float(gui.slider_volumen.get()))
                    ch.play(snd)
                    while ch.get_busy(): time.sleep(0.05)
        except Exception as e: gui.agregar_log(f"[Error TTS]: {e}")
        finally:
            cola_mensajes.task_done()
            gui.root.after(0, lambda: gui.lbl_cola.config(text=f"En cola: {cola_mensajes.qsize()}/50"))

threading.Thread(target=procesar_audio, daemon=True).start()

def enviar_a_voz(msg, forzar=False):
    if not gui.conectado and not forzar: return
    try:
        cola_mensajes.put(msg, timeout=0.2)
        gui.agregar_log(f"[AUDIO] {msg}")
    except queue.Full: pass

def procesar_comandos_musica(comentario, username):
    global cancion_actual
    partes = comentario.split(" ", 1)
    cmd = partes[0].lower()
    arg = partes[1].strip() if len(partes) > 1 else ""
    user_name = normalizar_texto(username) or "Usuario"

    if cmd in gui.obtener_lista_comandos(gui.entry_cmd_play):
        if arg:
            cola_musica.append((arg, user_name))
            gui.actualizar_lista_musica_ui()
            gui.agregar_log(f"[MÚSQUEDA] @{user_name} añadió: {arg}")
            enviar_a_voz(f"Canción añadida por {user_name}")
        return True
    elif cmd in gui.obtener_lista_comandos(gui.entry_cmd_skip):
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        return True
    elif cmd in gui.obtener_lista_comandos(gui.entry_cmd_stop):
        cola_musica.clear()
        gui.actualizar_lista_musica_ui()
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        return True
    return False

def iniciar_tiktok(unique_id):
    global TIEMPO_INICIO, CONTADOR_LIKES_GENERAL
    try:
        gui.actualizar_estado(f"Conectando a {unique_id}...", "#f9e2af")
        gui.client_tiktok = TikTokLiveClient(unique_id=unique_id)

        @gui.client_tiktok.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            global TIEMPO_INICIO, CONTADOR_LIKES_GENERAL
            gui.conectado = True
            gui.tiempo_conexion_inicio = time.time()
            TIEMPO_INICIO = time.time()
            CONTADOR_LIKES_GENERAL = 0
            LIKES_POR_USUARIO.clear()
            HISTORIAL_RECIENTE.clear()
            gui.actualizar_estado(f"Conectado a @{event.unique_id}", "#a6e3a1")

        @gui.client_tiktok.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            if not gui.conectado or time.time() - TIEMPO_INICIO < 2: return
            user = event.user
            username = str(getattr(user, "unique_id", "")).lower()
            nickname = str(getattr(user, "nickname", username))
            comentario = event.comment.strip()

            if comentario.startswith("!") and procesar_comandos_musica(comentario, nickname): return

            for p in gui.obtener_palabras_censuradas():
                if p in comentario.lower(): return

            id_msg = f"{username}:{comentario}"
            if id_msg in HISTORIAL_RECIENTE: return
            HISTORIAL_RECIENTE.append(id_msg)

            nombre_limpio = extraer_o_limpiar_emojis(nickname, 1) or "Usuario"
            max_c = int(gui.entry_limite.get() or 100)
            com_proc = aplicar_diccionario_reemplazos(comentario[:max_c], gui.obtener_diccionario_reemplazos())
            
            STATS["comentarios"] += 1
            gui.actualizar_metricas_ui()
            enviar_a_voz(f"{nombre_limpio} dice: {extraer_o_limpiar_emojis(com_proc, 3)}")

        @gui.client_tiktok.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            if not gui.conectado: return
            nick = getattr(event.user, "nickname", "Alguien")
            gift = getattr(event.gift, "name", "regalo")
            STATS["regalos"] += 1
            gui.actualizar_metricas_ui()
            if gui.alerta_regalos.get():
                reproducir_sonido_url(gui.entry_url_regalo.get())
                enviar_a_voz(f"¡Gracias {normalizar_texto(nick)} por {gift}!")

        @gui.client_tiktok.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            if not gui.conectado: return
            STATS["follows"] += 1
            gui.actualizar_metricas_ui()
            if gui.alerta_follows.get(): reproducir_sonido_url(gui.entry_url_follow.get())

        @gui.client_tiktok.on(LikeEvent)
        async def on_like(event: LikeEvent):
            global CONTADOR_LIKES_GENERAL
            if not gui.conectado: return
            lks = int(getattr(event, "likes", 1) or 1)
            STATS["likes_totales"] += lks
            gui.actualizar_metricas_ui()
            if gui.alerta_likes_general.get():
                CONTADOR_LIKES_GENERAL += lks
                if CONTADOR_LIKES_GENERAL >= gui.obtener_meta_likes_general():
                    reproducir_sonido_url(gui.entry_url_like_general.get())
                    CONTADOR_LIKES_GENERAL = 0

        gui.client_tiktok.run()
    except Exception as e:
        gui.conectado = False
        gui.actualizar_estado("Error Conexión", "#f38ba8")
        gui.agregar_log(f"[Error TikTok]: {e}")

gui.root.mainloop()
