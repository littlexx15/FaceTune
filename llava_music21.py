import streamlit as st
st.set_page_config(page_title="MetaTone Lab", layout="wide")

import sys
import os
import subprocess
import tempfile
import json
import numpy as np
from PIL import Image
from streamlit_drawable_canvas import st_canvas
import random
import music21
import pyphen
from midi2audio import FluidSynth
import torch

print("Python executable:", sys.executable)

# =============== 你的辅助函数 ===============
from util.image_helper import create_temp_file
from util.llm_helper import analyze_image_file, stream_parser

# =============== SoundFont 路径（请确保路径正确）===============
SOUNDFONT_PATH = "/Users/xiangxiaoxin/Documents/GitHub/FaceTune/soundfonts/VocalsPapel.sf2"

# =============== session_state 存储歌词和标题 ===============
if "lyrics" not in st.session_state:
    st.session_state["lyrics"] = None
if "song_title" not in st.session_state:
    st.session_state["song_title"] = None

# =============== 页面样式（仅调用一次）===============
st.markdown(
    """
    <style>
    .main .block-container { max-width: 1200px; margin: auto; }
    h1 { text-align: center; font-size: 36px !important; margin-bottom: 0.2em; }
    .subheader-text { font-size: 20px; font-weight: bold; margin-bottom: 0.6em; margin-top: 0.2em; }
    .song-title { font-size: 24px; font-weight: bold; margin-top: 0.5em; margin-bottom: 0.5em; }
    .lyrics-container { height: 500px; overflow-y: auto; padding-right: 1em; margin-top: 10px; border: 1px solid #ccc; border-radius: 5px; }
    .lyrics-container p { line-height: 1.6; margin-bottom: 0.8em; margin-left: 0.5em; margin-right: 0.5em; }
    .stButton { margin-top: 1em; margin-bottom: 1em; }
    div[data-baseweb="slider"] { width: 500px !important; }
    </style>
    """,
    unsafe_allow_html=True
)
st.markdown("<h1>MetaTone 实验室</h1>", unsafe_allow_html=True)


# =============== 1) 生成歌词 (调用 llava:7b) ===============
def generate_lyrics_with_ollama(image: Image.Image) -> str:
    """调用 llava:7b 模型，根据图像生成英文歌词。"""
    temp_path = create_temp_file(image)
    prompt = """
You are a creative songwriting assistant.
Please look at the image I provide and write a structured poetic song inspired by the visual content.

**Requirements**:
1. The song must include [Verse], [Chorus], and optionally [Bridge].
2. Capture deep emotions, vivid imagery, and a dynamic sense of movement.
3. Each section should introduce new elements, avoiding repetitive phrases.
4. Keep lines concise, naturally rhythmic, and easy to sing.
5. Verses should be introspective and descriptive, while the chorus should be impactful, emotionally intense, and memorable.
6. Build emotional tension and resolution within the narrative.

Now here is the image:
    """
    stream = analyze_image_file(image_file=temp_path, model="llava:7b", user_prompt=prompt)
    parsed = stream_parser(stream)
    lyrics = "".join(parsed).strip()
    return lyrics.strip('"')


# =============== 2) 生成歌曲标题 (调用 llava:7b) ===============
def generate_song_title(image: Image.Image) -> str:
    """调用 llava:7b 模型，为图像生成歌曲标题。"""
    temp_path = create_temp_file(image)
    prompt = """
Provide a concise, creative, and poetic song title. Only output the title, with no extra words or disclaimers.
    """
    stream = analyze_image_file(image_file=temp_path, model="llava:7b", user_prompt=prompt)
    parsed = stream_parser(stream)
    title = "".join(parsed).strip()
    return title.strip('"')


# =============== 3) 格式化歌词 ===============
def format_text(text: str) -> str:
    """去除多余空行，并保证每行首字母大写。"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    lines = [l[0].upper() + l[1:] if l else "" for l in lines]
    return "\n\n".join(lines)


# =============== 4) 基于歌词生成匹配的旋律 MIDI（带音节到 note.lyric） ===============

def split_into_syllables(line: str) -> list:
    """将整行拆分为音节或单词。也可以改成更精细的拆分逻辑。"""
    dic = pyphen.Pyphen(lang='en')
    words = line.split()
    syllables = []
    for word in words:
        syl = dic.inserted(word)  # "Hello" -> "Hel-lo"
        splitted = syl.split('-')
        # 打印调试：看看每个 word -> splitted 的结果
        print(f"[DEBUG] word={word}, splitted={splitted}")
        syllables.extend(splitted)
    return syllables

def generate_melody_for_line(line: str) -> list:
    """给一行歌词生成音符，默认音阶C大调C4~B4，时值1拍。"""
    scale_notes = ["C4", "D4", "E4", "F4", "G4", "A4", "B4"]
    # 拆成音节
    syllables = split_into_syllables(line)
    melody = []
    for i, syl in enumerate(syllables):
        pitch = scale_notes[i % len(scale_notes)]
        melody.append((pitch, 1.0, syl))
    return melody

def generate_melody_from_lyrics(lyrics: str, debug_save: bool = False) -> bytes:
    """
    使用Music21生成MIDI，并把每个音节写到 note.lyric。
    如果 debug_save=True，会额外保存为 debug_midi.mid，方便用MuseScore等查看歌词。
    """
    from music21 import stream, note, instrument
    s = stream.Stream()
    inst = instrument.Instrument()
    inst.midiProgram = 53
    s.insert(0, inst)

    lines = [l for l in lyrics.split("\n") if l.strip()]
    for line in lines:
        melody_line = generate_melody_for_line(line)
        for (pitch, dur, syl) in melody_line:
            n = note.Note(pitch, quarterLength=dur)
            n.lyric = syl  # 在音符上写入歌词
            # 打印调试：查看每个音符的 lyric
            print(f"[DEBUG] note={pitch}, lyric={repr(syl)}")
            s.append(n)

    # 写入临时MIDI
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        midi_path = tmp.name
    s.write("midi", fp=midi_path)

    # 读出二进制
    with open(midi_path, "rb") as f:
        midi_bytes = f.read()

    # 如果需要调试保存
    if debug_save:
        with open("debug_midi.mid", "wb") as debug_file:
            debug_file.write(midi_bytes)
        print("已保存 debug_midi.mid，可用MuseScore等工具查看是否带Lyric事件。")

    os.remove(midi_path)
    return midi_bytes

def generate_matched_melody(lyrics: str, debug_save: bool = False) -> bytes:
    """从歌词生成对应的 MIDI 文件并返回其二进制内容。"""
    return generate_melody_from_lyrics(lyrics, debug_save=debug_save)


# =============== 5) MIDI -> WAV（粗糙演唱） ===============
def midi_to_wav(midi_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp_midi:
        midi_path = tmp_midi.name
        tmp_midi.write(midi_bytes)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        wav_path = tmp_wav.name
    fs = FluidSynth(sound_font=SOUNDFONT_PATH)
    fs.midi_to_audio(midi_path, wav_path)
    with open(wav_path, "rb") as f:
        wav_data = f.read()
    os.remove(midi_path)
    os.remove(wav_path)
    return wav_data


# =============== 6) So‑VITS‑SVC 推理函数 ===============
def so_vits_svc_infer(rough_wav: bytes, svc_config: str, svc_model: str) -> bytes:
    """
    将基础音频 rough_wav 输入 So‑VITS‑SVC 推理脚本，转换为更自然的英文歌声。
    """
    svc_repo = "/Users/xiangxiaoxin/Documents/GitHub/so-vits-svc"
    raw_dir = os.path.join(svc_repo, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    raw_name = "temp_infer.wav"
    raw_path = os.path.join(svc_repo, "raw", raw_name)

    with open(raw_path, "wb") as f:
        f.write(rough_wav)

    # 也额外保存一份到当前项目，用于调试
    with open("debug_rough.wav", "wb") as f:
        f.write(rough_wav)

    cmd = [
        "python",
        os.path.join(svc_repo, "inference_main.py"),
        "-m", svc_model,
        "-c", svc_config,
        "-n", "temp_infer",
        "-t", "0",
        "-s", "hal-9000"
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, cwd=svc_repo)
        st.write("So‑VITS‑SVC 推理输出:", result.stdout)
    except subprocess.CalledProcessError as e:
        st.error("So‑VITS‑SVC 推理失败，错误信息:")
        st.error(e.stderr)
        raise

    out_file = os.path.join(svc_repo, "results", "temp_infer_0key_hal-9000_sovits_pm.flac")
    if not os.path.exists(out_file):
        files_in_results = os.listdir(os.path.join(svc_repo, "results"))
        raise FileNotFoundError(
            f"无法找到输出文件：{out_file}\n结果文件夹内容: {files_in_results}"
        )

    with open(out_file, "rb") as f:
        converted_data = f.read()
    return converted_data


# =============== 7) Streamlit 主 UI ===============
col_left, col_right = st.columns([1.4, 1.6], gap="medium")

with col_left:
    st.markdown("**在这里画画**", unsafe_allow_html=True)
    st.write("选择画笔颜色和笔刷大小，自由绘制创意画面。")

    brush_color = st.color_picker("画笔颜色", value="#000000")
    brush_size = st.slider("画笔大小", 1, 50, value=5)

    canvas_result = st_canvas(
        fill_color="rgba(255, 255, 255, 0)",
        stroke_width=brush_size,
        stroke_color=brush_color,
        background_color="white",
        update_streamlit=True,
        width=550,
        height=550,
        drawing_mode="freedraw",
        key="canvas",
    )

with col_right:
    st.markdown("**生成结果**", unsafe_allow_html=True)
    st.write("完成绘画后，可生成歌词、基础演唱，再用 So‑VITS‑SVC 转换为自然的英文歌声。")

    # 生成歌词
    if st.button("🎶 生成歌词"):
        if canvas_result.image_data is None:
            st.error("请先在左侧画布上绘制内容！")
        else:
            image = Image.fromarray((canvas_result.image_data * 255).astype(np.uint8)).convert("RGB")
            title = generate_song_title(image)
            raw_lyrics = generate_lyrics_with_ollama(image)
            lyrics = format_text(raw_lyrics)
            st.session_state["song_title"] = title
            st.session_state["lyrics"] = lyrics

    # 显示生成的歌词和标题
    if st.session_state["song_title"] and st.session_state["lyrics"]:
        st.markdown(f"**歌曲标题：** {st.session_state['song_title']}", unsafe_allow_html=True)
        lyrics_html = st.session_state["lyrics"].replace("\n", "<br>")
        st.markdown(f"<div class='lyrics-container'><p>{lyrics_html}</p></div>", unsafe_allow_html=True)

    # 生成基础演唱（MIDI→WAV）
    if st.button("🎤 生成基础演唱"):
        if not st.session_state["lyrics"]:
            st.error("请先生成歌词！")
        else:
            # 这里 debug_save=True 用于保存 debug_midi.mid
            midi_bytes = generate_matched_melody(st.session_state["lyrics"], debug_save=True)
            rough_wav = midi_to_wav(midi_bytes)
            st.audio(rough_wav, format="audio/wav")
            st.download_button("下载基础演唱 WAV", rough_wav, "rough_melody.wav", mime="audio/wav")

    # 使用 So‑VITS‑SVC 生成自然演唱
    if st.button("🎤 生成 So‑VITS‑SVC 演唱"):
        if not st.session_state["lyrics"]:
            st.error("请先生成歌词！")
        else:
            midi_bytes = generate_matched_melody(st.session_state["lyrics"], debug_save=True)
            rough_wav = midi_to_wav(midi_bytes)
            svc_config = "/Users/xiangxiaoxin/Documents/GitHub/FaceTune/configs/config.json"
            svc_model = "/Users/xiangxiaoxin/Documents/GitHub/FaceTune/models/G_800.pth"
            converted_wav = so_vits_svc_infer(rough_wav, svc_config, svc_model)
            st.audio(converted_wav, format="audio/wav")
            st.download_button("下载 So‑VITS‑SVC 演唱 WAV", converted_wav, "converted_singing.flac", mime="audio/flac")
