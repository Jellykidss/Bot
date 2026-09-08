import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
from keep_alive import keep_alive

# กำหนด Intent ของบอท
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ตั้งค่า yt-dlp แบบอัปเดตเพื่อเลี่ยงบอทบล็อก
ytdl_format_options = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'ytsearch',
    'extract_flat': False,
    # ปรับใช้ client หลากหลายรูปแบบเพื่อป้องกันการบล็อก IP บน Cloud
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'tv_embedded', 'mweb']
        }
    },
}

ffmpeg_options = {
    'options': '-vn -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# ตัวแปรเก็บสถานะการวนซ้ำเพลง
loop_status = {}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

# --- Slash Command: /join ---
@bot.tree.command(name="join", description="ให้บอทเชื่อมต่อเข้าห้องเสียง")
async def slash_join(interaction: discord.Interaction):
    if interaction.user.voice and interaction.user.voice.channel:
        channel = interaction.user.voice.channel
        voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
        
        if voice_client and voice_client.is_connected():
            await voice_client.move_to(channel)
            await interaction.response.send_message(f"ย้ายเข้ามาที่ห้อง **{channel.name}** เรียบร้อยแล้วครับ!", ephemeral=True)
        else:
            try:
                await channel.connect()
                await interaction.response.send_message(f"เชื่อมต่อเข้าห้อง **{channel.name}** เรียบร้อยแล้วครับ!", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"เกิดข้อผิดพลาด: {e}", ephemeral=True)
    else:
        await interaction.response.send_message("คุณต้องอยู่ในห้องเสียงก่อนจึงจะใช้คำสั่งนี้ได้!", ephemeral=True)

# --- Slash Command: /leave ---
@bot.tree.command(name="leave", description="ให้บอทออกจากห้องเสียง")
async def slash_leave(interaction: discord.Interaction):
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.is_connected():
        loop_status[interaction.guild.id] = False
        await voice_client.disconnect()
        await interaction.response.send_message("ออกจากห้องเสียงเรียบร้อยแล้วครับ!", ephemeral=True)
    else:
        await interaction.response.send_message("บอทไม่ได้อยู่ในห้องเสียงในขณะนี้ครับ!", ephemeral=True)

# --- Slash Command: /play ---
@bot.tree.command(name="play", description="เล่นเพลงจากชื่อเพลงหรือลิงก์ Spotify")
@app_commands.describe(search="พิมพ์ชื่อเพลง ศิลปิน หรือวางลิงก์เพลงจาก Spotify")
async def slash_play(interaction: discord.Interaction, search: str):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("คุณต้องอยู่ในห้องเสียงก่อนจึงจะเปิดเพลงได้!", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    channel = interaction.user.voice.channel
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)

    if not voice_client:
        try:
            voice_client = await channel.connect()
        except Exception as e:
            await interaction.followup.send(f"ไม่สามารถเชื่อมต่อห้องเสียงได้: {e}")
            return
    elif voice_client.channel != channel:
        await voice_client.move_to(channel)

    try:
        query = search
        # ดึงข้อมูลชื่อเพลงจากลิงก์ Spotify
        if "spotify.com" in search:
            import urllib.request
            import json
            try:
                oembed_url = f"https://open.spotify.com/oembed?url={search}"
                req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    data_json = json.loads(response.read().decode())
                    query = data_json.get('title', search)
            except Exception as err:
                print(f"Spotify oembed error: {err}")

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        
        if 'entries' in data:
            data = data['entries'][0]

        song_url = data.get('url')
        song_title = data.get('title', 'เพลงไม่มีชื่อ')

        def play_next(error):
            if error:
                print(f"Player error: {error}")
            guild_id = interaction.guild.id
            if loop_status.get(guild_id, False):
                try:
                    player = discord.FFmpegPCMAudio(song_url, **ffmpeg_options)
                    voice_client.play(player, after=play_next)
                except Exception as e:
                    print(f"Error looping song: {e}")

        if voice_client.is_playing():
            voice_client.stop()

        player = discord.FFmpegPCMAudio(song_url, **ffmpeg_options)
        voice_client.play(player, after=play_next)

        await interaction.followup.send(f"กำลังเล่นเพลง: **{song_title}** 🎵")
    except Exception as e:
        await interaction.followup.send(f"เกิดข้อผิดพลาดในการเล่นเพลง: {e}")

# --- Slash Command: /loop ---
@bot.tree.command(name="loop", description="เปิด/ปิด การวนซ้ำเพลงปัจจุบัน")
async def slash_loop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    current_status = loop_status.get(guild_id, False)
    loop_status[guild_id] = not current_status
    
    if loop_status[guild_id]:
        await interaction.response.send_message("🔁 เปิดใช้งานโหมด **วนซ้ำเพลงปัจจุบัน** เรียบร้อยแล้วครับ!", ephemeral=True)
    else:
        await interaction.response.send_message("➡️ ปิดการใช้งานโหมด **วนซ้ำ** แล้วครับ", ephemeral=True)

# --- Slash Command: /stop ---
@bot.tree.command(name="stop", description="หยุดเพลงที่กำลังเล่นอยู่")
async def slash_stop(interaction: discord.Interaction):
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.is_playing():
        loop_status[interaction.guild.id] = False
        voice_client.stop()
        await interaction.response.send_message("⏹️ หยุดเพลงเรียบร้อยแล้วครับ", ephemeral=True)
    else:
        await interaction.response.send_message("ไม่มีเพลงกำลังเล่นอยู่ในขณะนี้ครับ!", ephemeral=True)

keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
