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

# ----------------- ระบบประกาศข้อความ (Modal) -----------------
class AnnouncementModal(discord.ui.Modal, title="สร้างข้อความประกาศ"):
    def __init__(self, channel: discord.TextChannel):
        super().__init__()
        self.channel = channel

    announcement_text = discord.ui.TextInput(
        label="เนื้อหาประกาศ (กด Enter เพื่อขึ้นบรรทัดใหม่ได้)",
        style=discord.TextStyle.paragraph,
        placeholder="พิมพ์ข้อความของคุณที่นี่...",
        required=True,
        max_length=3500
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            sent_msg = await self.channel.send(content=self.announcement_text.value)
            await interaction.response.send_message(
                f"✅ ส่งประกาศไปยังห้อง {self.channel.mention} เรียบร้อยแล้ว!\n*(ID ข้อความสำหรับแก้ไข: `{sent_msg.id}`)*", 
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาดในการส่งประกาศ: {e}", ephemeral=True)

@bot.tree.command(name="announcement", description="เปิดหน้าต่างเขียนประกาศ (สามารถขึ้นบรรทัดใหม่ได้)")
@app_commands.describe(channel="เลือกห้องแชทที่ต้องการส่งประกาศ")
async def slash_announcement(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องมีสิทธิ์ Manage Channels)", ephemeral=True)
        return
    await interaction.response.send_modal(AnnouncementModal(channel))

# ----------------- ระบบแก้ไขข้อความประกาศ (Modal) -----------------
class EditAnnouncementModal(discord.ui.Modal, title="แก้ไขข้อความประกาศ"):
    def __init__(self, channel: discord.TextChannel, message_id: str, old_content: str):
        super().__init__()
        self.channel = channel
        self.message_id = message_id
        self.new_announcement_text.default = old_content

    new_announcement_text = discord.ui.TextInput(
        label="เนื้อหาใหม่ (กด Enter เพื่อขึ้นบรรทัดใหม่ได้)",
        style=discord.TextStyle.paragraph,
        placeholder="แก้ไขข้อความของคุณที่นี่...",
        required=True,
        max_length=3500
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            msg_id_int = int(self.message_id)
            msg_to_edit = await self.channel.fetch_message(msg_id_int)
            
            if msg_to_edit.author != bot.user:
                await interaction.response.send_message("❌ ไม่สามารถแก้ไขข้อความนี้ได้ เนื่องจากไม่ใช่ข้อความที่บอทส่ง", ephemeral=True)
                return

            await msg_to_edit.edit(content=self.new_announcement_text.value)
            await interaction.response.send_message("✅ แก้ไขข้อความประกาศเรียบร้อยแล้วครับ!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ Message ID ไม่ถูกต้อง (ต้องเป็นตัวเลข)", ephemeral=True)
        except discord.NotFound:
            await interaction.response.send_message("❌ ไม่พบข้อความตาม ID ที่ระบุในห้องนี้", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

@bot.tree.command(name="edit_announcement", description="เปิดหน้าต่างแก้ไขข้อความประกาศ")
@app_commands.describe(
    channel="ห้องแชทที่ข้อความประกาศนั้นอยู่",
    message_id="ID ของข้อความประกาศที่ต้องการแก้ไข"
)
async def slash_edit_announcement(interaction: discord.Interaction, channel: discord.TextChannel, message_id: str):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
        return

    try:
        msg_id_int = int(message_id)
        msg_to_edit = await channel.fetch_message(msg_id_int)
        
        if msg_to_edit.author != bot.user:
            await interaction.response.send_message("❌ ข้อความนี้ไม่ใช่ข้อความที่บอทส่ง จึงไม่สามารถแก้ไขผ่านบอทได้", ephemeral=True)
            return

        await interaction.response.send_modal(EditAnnouncementModal(channel, message_id, msg_to_edit.content))
    except ValueError:
        await interaction.response.send_message("❌ Message ID ไม่ถูกต้อง (ต้องเป็นตัวเลข)", ephemeral=True)
    except discord.NotFound:
        await interaction.response.send_message("❌ ไม่พบข้อความตาม ID ที่ระบุ กรุณาตรวจสอบ ID อีกครั้ง", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)


# ----------------- ระบบจัดการ Ticket แบบ Pop-up เมนูรวม 3 โหมด -----------------

# 1. Select Menu สำหรับปิดห้องเดี่ยว
class SingleTicketSelect(discord.ui.Select):
    def __init__(self, channels):
        options = [discord.SelectOption(label=ch.name[:100], value=str(ch.id), description=f"หมวดหมู่: {ch.category.name if ch.category else 'ไม่มี'}") for ch in channels[:25]]
        super().__init__(placeholder="📌 เลือกห้อง Ticket ที่ต้องการปิด (1 ห้อง)", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ch = interaction.guild.get_channel(int(self.values[0]))
        if ch:
            try:
                name = ch.name
                await ch.delete(reason=f"Closed by {interaction.user}")
                await interaction.followup.send(f"🗑️ ปิดห้อง Ticket **{name}** เรียบร้อยแล้วครับ!", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"❌ ไม่สามารถปิดห้องนี้ได้: {e}", ephemeral=True)
        else:
            await interaction.followup.send("❌ ไม่พบห้องดังกล่าวแล้ว", ephemeral=True)

class SingleTicketView(discord.ui.View):
    def __init__(self, channels):
        super().__init__(timeout=120)
        self.add_item(SingleTicketSelect(channels))


# 2. Select Menu สำหรับเลือกปิดหลายห้อง (3-5 หรือมากกว่า)
class MultiTicketSelect(discord.ui.Select):
    def __init__(self, channels):
        options = [discord.SelectOption(label=ch.name[:100], value=str(ch.id), description=f"หมวดหมู่: {ch.category.name if ch.category else 'ไม่มี'}") for ch in channels[:25]]
        super().__init__(placeholder="📌 เลือกห้อง Ticket ที่ต้องการปิด (เลือกได้หลายห้อง)", min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        closed_count = 0
        for channel_id in self.values:
            ch = interaction.guild.get_channel(int(channel_id))
            if ch:
                try:
                    await ch.delete(reason=f"Multi-closed by {interaction.user}")
                    closed_count += 1
                    await asyncio.sleep(0.4)
                except Exception as e:
                    print(f"Failed to delete channel: {e}")

        await interaction.followup.send(f"✅ ปิดห้อง Ticket ที่เลือกสำเร็จทั้งหมด **{closed_count}** ห้องแล้วครับ!", ephemeral=True)

class MultiTicketView(discord.ui.View):
    def __init__(self, channels):
        super().__init__(timeout=120)
        self.add_item(MultiTicketSelect(channels))


# 3. หน้าต่างหลัก Pop-up เลือกโหมดจัดการ Ticket
class TicketManageView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=120)
        self.guild = guild

    @discord.ui.button(label="🗑️ ปิดห้องเดียว", style=discord.ButtonStyle.primary, custom_id="btn_single")
    async def btn_single(self, interaction: discord.Interaction, button: discord.ui.Button):
        channels = [ch for ch in self.guild.text_channels if "ticket" in ch.name.lower() or "تيكيت" in ch.name.lower()]
        if not channels:
            await interaction.response.send_message("⚠️ ไม่พบห้อง Ticket ในขณะนี้ครับ", ephemeral=True)
            return
        await interaction.response.send_message("📋 กรุณาเลือกห้อง Ticket ที่ต้องการปิด (1 ห้อง):", view=SingleTicketView(channels), ephemeral=True)

    @discord.ui.button(label="☑️ เลือกปิดหลายห้อง", style=discord.ButtonStyle.success, custom_id="btn_multi")
    async def btn_multi(self, interaction: discord.Interaction, button: discord.ui.Button):
        channels = [ch for ch in self.guild.text_channels if "ticket" in ch.name.lower() or "تيكيت" in ch.name.lower()]
        if not channels:
            await interaction.response.send_message("⚠️ ไม่พบห้อง Ticket ในขณะนี้ครับ", ephemeral=True)
            return
        await interaction.response.send_message("📋 กรุณาเลือกห้อง Ticket ที่ต้องการปิด (ติ๊กเลือกหลายห้องได้):", view=MultiTicketView(channels), ephemeral=True)

    @discord.ui.button(label="🚨 ปิดห้องทั้งหมด", style=discord.ButtonStyle.danger, custom_id="btn_all")
    async def btn_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ คำสั่งนี้ต้องใช้สิทธิ์ผู้ดูแลระบบ (Administrator) เท่านั้น", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        channels_to_delete = [ch for ch in self.guild.text_channels if "ticket" in ch.name.lower() or "تيكيت" in ch.name.lower()]
        
        if not channels_to_delete:
            await interaction.followup.send("⚠️ ไม่พบห้อง Ticket ที่ต้องปิด", ephemeral=True)
            return

        closed_count = 0
        for ch in channels_to_delete:
            try:
                await ch.delete(reason=f"Bulk closed via Pop-up by {interaction.user}")
                closed_count += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Failed to delete channel: {e}")

        await interaction.followup.send(f"✅ ปิดห้อง Ticket ทั้งหมดสำเร็จ **{closed_count}** ห้องแล้วครับ!", ephemeral=True)


@bot.tree.command(name="ticket_manage", description="เปิดหน้าต่าง Pop-up เลือกวิธีปิดห้อง Ticket (ห้องเดียว, หลายห้อง, หรือทั้งหมด)")
async def slash_ticket_manage(interaction: discord.SystemInteraction or discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
        return

    view = TicketManageView(interaction.guild)
    await interaction.response.send_message("🎫 **ระบบจัดการห้อง Ticket**\nกรุณาเลือกรูปแบบการปิดห้องที่คุณต้องการจากปุ่มด้านล่างนี้ครับ:", view=view, ephemeral=True)


keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
