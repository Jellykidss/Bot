import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import urllib.request
import json
from keep_alive import keep_alive

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

ytdl_format_options = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'scsearch10',
    'extract_flat': False,
    'socket_timeout': 15,
}

ffmpeg_options = {
    'options': '-vn -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

queues = {}
loop_status = {}
current_song = {}

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

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

@bot.tree.command(name="leave", description="ให้บอทออกจากห้องเสียง")
async def slash_leave(interaction: discord.Interaction):
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.is_connected():
        guild_id = interaction.guild.id
        queues[guild_id] = []
        loop_status[guild_id] = False
        current_song.pop(guild_id, None)
        await voice_client.disconnect()
        await interaction.response.send_message("ออกจากห้องเสียงเรียบร้อยแล้วครับ!", ephemeral=True)
    else:
        await interaction.response.send_message("บอทไม่ได้อยู่ในห้องเสียงในขณะนี้ครับ!", ephemeral=True)

def play_next(guild_id, voice_client):
    if guild_id not in queues:
        queues[guild_id] = []
    
    # ถ้าเปิด loop อยู่ ให้ดึงข้อมูลเพลงใหม่เพื่อแก้ปัญหาลิงก์หมดอายุ (403 Forbidden)
    if loop_status.get(guild_id, False) and guild_id in current_song:
        try:
            query = current_song[guild_id]['title']
            data = ytdl.extract_info(query, download=False)
            if 'entries' in data:
                song_data = data['entries'][0]
            else:
                song_data = data
            
            fresh_url = song_data.get('url')
            if fresh_url:
                player = discord.FFmpegPCMAudio(fresh_url, **ffmpeg_options)
                voice_client.play(player, after=lambda e: play_next(guild_id, voice_client))
                return
        except Exception as e:
            print(f"Error refreshing loop song: {e}")

    # เล่นเพลงถัดไปในคิว
    if len(queues[guild_id]) > 0:
        next_song = queues[guild_id].pop(0)
        current_song[guild_id] = next_song
        song_url = next_song['url']
        try:
            player = discord.FFmpegPCMAudio(song_url, **ffmpeg_options)
            voice_client.play(player, after=lambda e: play_next(guild_id, voice_client))
        except Exception as e:
            print(f"Error playing next song: {e}")
    else:
        current_song.pop(guild_id, None)

@bot.tree.command(name="play", description="เล่นเพลงทันทีหรือเพิ่มเข้าคิวเพลง")
@app_commands.describe(search="พิมพ์ชื่อเพลง ศิลปิน หรือวางลิงก์เพลง")
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
        if "spotify.com" in search:
            try:
                oembed_url = f"https://open.spotify.com/oembed?url={search}"
                req = urllib.request.Request(oembed_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req) as response:
                    data_json = json.loads(response.read().decode())
                    query = data_json.get('title', search)
            except Exception as err:
                print(f"Spotify oembed error: {err}")

        loop = asyncio.get_event_loop()
        
        def extract_valid_song():
            data = ytdl.extract_info(query, download=False)
            if 'entries' in data:
                for entry in data['entries']:
                    if entry:
                        try:
                            sub_url = entry.get('url')
                            if sub_url and not entry.get('is_live', False):
                                return entry
                        except Exception:
                            continue
                raise Exception("เพลงนี้ถูกป้องกันลิขสิทธิ์ (DRM) ทุกเวอร์ชัน กรุณาลองค้นหาด้วยชื่ออื่นครับ")
            return data

        data = await loop.run_in_executor(None, extract_valid_song)

        song_url = data.get('url')
        song_title = data.get('title', 'เพลงไม่มีชื่อ')
        guild_id = interaction.guild.id

        song_info = {'url': song_url, 'title': song_title}

        if guild_id not in queues:
            queues[guild_id] = []

        if voice_client.is_playing() or voice_client.is_paused():
            queues[guild_id].append(song_info)
            queue_position = len(queues[guild_id])
            await interaction.followup.send(f"➕ เพิ่มเข้าคิวลำดับที่ **{queue_position}**: **{song_title}** 🎵")
        else:
            current_song[guild_id] = song_info
            player = discord.FFmpegPCMAudio(song_url, **ffmpeg_options)
            voice_client.play(player, after=lambda e: play_next(guild_id, voice_client))
            await interaction.followup.send(f"กำลังเล่นเพลง: **{song_title}** 🎵")

    except Exception as e:
        await interaction.followup.send(f"เกิดข้อผิดพลาดในการเล่นเพลง: {e}")

@bot.tree.command(name="skip", description="ข้ามเพลงที่กำลังเล่นไปยังเพลงถัดไปในคิว")
async def slash_skip(interaction: discord.Interaction):
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงเรียบร้อยแล้วครับ!", ephemeral=True)
    else:
        await interaction.response.send_message("ไม่มีเพลงกำลังเล่นอยู่ให้ข้ามครับ!", ephemeral=True)

@bot.tree.command(name="queue", description="ดูรายชื่อเพลงทั้งหมดที่รออยู่ในคิว")
async def slash_queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id not in queues or len(queues[guild_id]) == 0:
        await interaction.response.send_message("📜 ไม่มีเพลงรออยู่ในคิวขณะนี้ครับ", ephemeral=True)
        return
    
    queue_text = ""
    for i, song in enumerate(queues[guild_id], 1):
        queue_text += f"**{i}.** {song['title']}\n"
    
    await interaction.response.send_message(f"📜 **คิวเพลงทั้งหมด:**\n{queue_text}", ephemeral=True)

@bot.tree.command(name="loop", description="เปิด/ปิด การวนซ้ำเพลงปัจจุบัน")
async def slash_loop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    current_status = loop_status.get(guild_id, False)
    loop_status[guild_id] = not current_status
    
    if loop_status[guild_id]:
        await interaction.response.send_message("🔁 เปิดใช้งานโหมด **วนซ้ำเพลงปัจจุบัน** เรียบร้อยแล้วครับ!", ephemeral=True)
    else:
        await interaction.response.send_message("➡️ ปิดการใช้งานโหมด **วนซ้ำ** แล้วครับ", ephemeral=True)

@bot.tree.command(name="stop", description="หยุดเพลงและล้างคิวทั้งหมด")
async def slash_stop(interaction: discord.Interaction):
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client:
        guild_id = interaction.guild.id
        queues[guild_id] = []
        loop_status[guild_id] = False
        current_song.pop(guild_id, None)
        if voice_client.is_playing():
            voice_client.stop()
        await interaction.response.send_message("⏹️ หยุดเพลงและล้างคิวทั้งหมดเรียบร้อยแล้วครับ", ephemeral=True)
    else:
        await interaction.response.send_message("บอทไม่ได้อยู่ในห้องเสียงครับ!", ephemeral=True)

keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
