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
ticket_roles = {}
feedback_channels = {}  # เก็บห้องรีวิวสาธารณะ
ticket_categories = {}  # เก็บ ID หมวดหมู่แยกตามประเภท {guild_id: {'buyer': id, 'sell': id, 'preorder': id}}
ticket_configs = {}     # เก็บการตั้งค่าหน้าตา Embed และรูปภาพแยกตามหมวดหมู่

# ฟังก์ชันตรวจสอบสิทธิ์ (แอดมิน หรือ มียศที่ตั้งค่าผ่าน /set_ticket_role)
def has_ticket_permission(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_channels:
        return True
    guild_id = interaction.guild.id
    if guild_id in ticket_roles:
        role = interaction.guild.get_role(ticket_roles[guild_id])
        if role and role in interaction.user.roles:
            return True
    return False

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
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

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
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

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
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

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
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("⏭️ ข้ามเพลงเรียบร้อยแล้วครับ!", ephemeral=True)
    else:
        await interaction.response.send_message("ไม่มีเพลงกำลังเล่นอยู่ให้ข้ามครับ!", ephemeral=True)

@bot.tree.command(name="queue", description="ดูรายชื่อเพลงทั้งหมดที่รออยู่ในคิว")
async def slash_queue(interaction: discord.Interaction):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

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
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

    guild_id = interaction.guild.id
    current_status = loop_status.get(guild_id, False)
    loop_status[guild_id] = not current_status
    
    if loop_status[guild_id]:
        await interaction.response.send_message("🔁 เปิดใช้งานโหมด **วนซ้ำเพลงปัจจุบัน** เรียบร้อยแล้วครับ!", ephemeral=True)
    else:
        await interaction.response.send_message("➡️ ปิดการใช้งานโหมด **วนซ้ำ** แล้วครับ", ephemeral=True)

@bot.tree.command(name="stop", description="หยุดเพลงและล้างคิวทั้งหมด")
async def slash_stop(interaction: discord.Interaction):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

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
        label="เนื้อหาประกาศ",
        style=discord.TextStyle.paragraph,
        placeholder="พิมพ์ข้อความของคุณที่นี่...",
        required=True,
        max_length=4000
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
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return
    await interaction.response.send_modal(AnnouncementModal(channel))

class EditAnnouncementModal(discord.ui.Modal, title="แก้ไขข้อความประกาศ"):
    def __init__(self, channel: discord.TextChannel, message_id: str, old_content: str):
        super().__init__()
        self.channel = channel
        self.message_id = message_id
        self.new_announcement_text.default = old_content

    new_announcement_text = discord.ui.TextInput(
        label="เนื้อหาใหม่",
        style=discord.TextStyle.paragraph,
        placeholder="แก้ไขข้อความของคุณที่นี่...",
        required=True,
        max_length=4000
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
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

@bot.tree.command(name="edit_announcement", description="เปิดหน้าต่างแก้ไขข้อความประกาศ")
@app_commands.describe(channel="ห้องแชทที่ข้อความประกาศอยู่", message_id="ID ของข้อความ")
async def slash_edit_announcement(interaction: discord.Interaction, channel: discord.TextChannel, message_id: str):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return
    try:
        msg_id_int = int(message_id)
        msg_to_edit = await channel.fetch_message(msg_id_int)
        await interaction.response.send_modal(EditAnnouncementModal(channel, message_id, msg_to_edit.content))
    except Exception as e:
        await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)


# ----------------- ระบบรับยศ (Role Panel & Dropdown) -----------------

class SingleRoleButtonView(discord.ui.View):
    def __init__(self, role: discord.Role, mode: str, button_label: str, emoji: str):
        super().__init__(timeout=None)
        self.role = role
        self.mode = mode 
        
        btn_style = discord.ButtonStyle.success if mode == 'claim_only' else discord.ButtonStyle.primary
        self.btn = discord.ui.Button(
            label=button_label if button_label else role.name, 
            style=btn_style, 
            emoji=emoji if emoji else "➕", 
            custom_id=f"role_btn_{role.id}_{mode}"
        )
        self.btn.callback = self.button_callback
        self.add_item(self.btn)

    async def button_callback(self, interaction: discord.Interaction):
        if self.mode == 'claim_only':
            if self.role in interaction.user.roles:
                await interaction.response.send_message(f"ℹ️ คุณมียศ **{self.role.name}** อยู่แล้วครับ", ephemeral=True)
            else:
                await interaction.user.add_roles(self.role)
                await interaction.response.send_message(f"✅ รับยศ **{self.role.name}** เรียบร้อยแล้วครับ!", ephemeral=True)
        else: 
            if self.role in interaction.user.roles:
                await interaction.user.remove_roles(self.role)
                await interaction.response.send_message(f"❌ ถอดรยศ **{self.role.name}** ออกจากคุณแล้วครับ", ephemeral=True)
            else:
                await interaction.user.add_roles(self.role)
                await interaction.response.send_message(f"✅ มอบยศ **{self.role.name}** ให้คุณเรียบร้อยแล้วครับ!", ephemeral=True)


class MultiRoleSelect(discord.ui.Select):
    def __init__(self, roles_list):
        options = []
        for r in roles_list[:25]:
            options.append(discord.SelectOption(label=r.name[:100], value=str(r.id), emoji="✨"))
        super().__init__(placeholder="📌 เลือกยศที่ต้องการรับ (เลือกได้หลายอัน)", min_values=1, max_values=len(options), options=options)
        self.roles_list = roles_list

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        added_roles = []
        removed_roles = []
        
        selected_role_ids = [int(v) for v in self.values]
        for r in self.roles_list:
            if r.id in selected_role_ids:
                if r not in interaction.user.roles:
                    await interaction.user.add_roles(r)
                    added_roles.append(r.name)
            else:
                if r in interaction.user.roles:
                    await interaction.user.remove_roles(r)
                    removed_roles.append(r.name)

        msg = "✅ อัปเดตสถานะยศของคุณเรียบร้อยแล้ว!\n"
        if added_roles:
            msg += f"• เพิ่มยศ: **{', '.join(added_roles)}**\n"
        if removed_roles:
            msg += f"• ถอดรยศ: **{', '.join(removed_roles)}**\n"
        if not added_roles and not removed_roles:
            msg = "ℹ️ ไม่มีข้อยศเปลี่ยนแปลง"

        await interaction.followup.send(msg, ephemeral=True)

class MultiRoleSelectView(discord.ui.View):
    def __init__(self, roles_list):
        super().__init__(timeout=None)
        self.add_item(MultiRoleSelect(roles_list))


@bot.tree.command(name="setup_role_panel", description="สร้างแผงรับยศ (เลือกปุ่มเดี่ยว หรือเมนู Dropdown เลือกหลายยศ)")
@app_commands.describe(
    channel="ห้องแชทที่ต้องการส่งแผง",
    panel_type="เลือกประเภทแผงยศ",
    role_1="ยศที่ 1",
    role_2="ยศที่ 2 (สำหรับ Dropdown)",
    role_3="ยศที่ 3 (สำหรับ Dropdown)",
    mode="(สำหรับปุ่มเดี่ยว) toggle=กดเปิด-ปิดได้เอง, claim_only=กดรับครั้งเดียวถอดไม่ได้",
    title_text="หัวข้อหลักของ Embed",
    description_text="รายละเอียดเพิ่มเติม",
    color="สีของกรอบ (green, red, blue, gold, purple)",
    image_url="ลิงก์รูปภาพ หรือ GIF ตกแต่ง",
    button_label="ข้อความบนปุ่ม",
    emoji="อีโมจิปุ่ม"
)
@app_commands.choices(panel_type=[
    app_commands.Choice(name="ปุ่มกด (Single Button)", value="button"),
    app_commands.Choice(name="เมนูเลือกหลายยศ (Dropdown Menu)", value="dropdown")
], mode=[
    app_commands.Choice(name="กดเปิด-ปิดได้ (Toggle)", value="toggle"),
    app_commands.Choice(name="กดรับแล้วถอดไม่ได้ (Claim Only)", value="claim_only")
])
async def slash_setup_role_panel(
    interaction: discord.Interaction, 
    channel: discord.TextChannel, 
    panel_type: app_commands.Choice[str],
    role_1: discord.Role,
    role_2: discord.Role = None,
    role_3: discord.Role = None,
    mode: app_commands.Choice[str] = None,
    title_text: str = "ระบบรับยศอัตโนมัติ",
    description_text: str = "กดปุ่มหรือเลือกเมนูด้านล่างเพื่อรับยศ",
    color: str = "blue",
    image_url: str = None,
    button_label: str = None,
    emoji: str = "➕"
):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

    embed_color = discord.Color.blurple()
    c_lower = color.lower()
    if c_lower == "green": embed_color = discord.Color.green()
    elif c_lower == "red": embed_color = discord.Color.red()
    elif c_lower == "gold": embed_color = discord.Color.gold()
    elif c_lower == "purple": embed_color = discord.Color.purple()

    embed = discord.Embed(title=title_text, description=description_text, color=embed_color)
    if image_url:
        embed.set_image(url=image_url)

    selected_type = panel_type.value
    if selected_type == "button":
        chosen_mode = mode.value if mode else "toggle"
        view = SingleRoleButtonView(role_1, chosen_mode, button_label, emoji)
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ สร้างแผงปุ่มกดรับยศ **{role_1.name}** ไปที่ห้อง {channel.mention} เรียบร้อยแล้วครับ!", ephemeral=True)
    elif selected_type == "dropdown":
        roles_list = [role_1]
        if role_2: roles_list.append(role_2)
        if role_3: roles_list.append(role_3)
        view = MultiRoleSelectView(roles_list)
        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ สร้างแผง Dropdown เลือกหลายยศไปที่ห้อง {channel.mention} เรียบร้อยแล้วครับ!", ephemeral=True)


# ----------------- ระบบตั้งค่าห้องรีวิวสาธารณะ -----------------

@bot.tree.command(name="set_feedback_channel", description="กำหนดห้องรีวิวสาธารณะ (โชว์ให้ลูกค้าคนอื่นเห็น)")
@app_commands.describe(channel="เลือกห้องแชทที่จะให้แสดงรีวิวสาธารณะ")
async def slash_set_feedback_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return
    feedback_channels[interaction.guild.id] = channel.id
    await interaction.response.send_message(f"✅ ตั้งค่าห้องรีวิวสาธารณะสำเร็จที่ห้อง {channel.mention}", ephemeral=True)


# ----------------- ระบบตั้งค่า Category สำหรับแยก Ticket -----------------

@bot.tree.command(name="set_ticket_categories", description="ตั้งค่าหมวดหมู่ (Category) สำหรับแยกประเภท Ticket 3 หมวด")
@app_commands.describe(
    buyer_category="หมวดหมู่สำหรับ สั่งซื้อเงินเอ็ม (Ticket Buyer)",
    sell_category="หมวดหมู่สำหรับ ขายเงินเอ็ม (Ticket Sell)",
    preorder_category="หมวดหมู่สำหรับ สั่งของในเมือง (Ticket Preorder)"
)
async def slash_set_ticket_categories(
    interaction: discord.Interaction, 
    buyer_category: discord.CategoryChannel, 
    sell_category: discord.CategoryChannel, 
    preorder_category: discord.CategoryChannel
):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return
    
    guild_id = interaction.guild.id
    ticket_categories[guild_id] = {
        'buyer': buyer_category.id,
        'sell': sell_category.id,
        'preorder': preorder_category.id
    }
    await interaction.response.send_message(
        f"✅ ตั้งค่าหมวดหมู่ Ticket เรียบร้อยแล้ว!\n"
        f"• สั่งซื้อเงินเอ็ม: **{buyer_category.name}**\n"
        f"• ขายเงินเอ็ม: **{sell_category.name}**\n"
        f"• สั่งของในเมือง: **{preorder_category.name}**", 
        ephemeral=True
    )


# ----------------- ระบบตั้งค่าหน้าตาต้อนรับในห้อง Ticket (แยกตามหมวดหมู่) -----------------

@bot.tree.command(name="set_ticket_config", description="ตั้งค่าข้อความ, หัวข้อ และรูปภาพ ในห้อง Ticket ของแต่ละหมวดหมู่")
@app_commands.describe(
    ticket_type="เลือกหมวดหมู่ที่ต้องการตั้งค่า",
    title_text="หัวข้อหลัก Embed (เช่น THNK FOR BUY)",
    description_text="ข้อความรายละเอียดในห้อง (เช่น ก่อนที่จะเสนอขายโปรดดูช่องรับเงิน...)",
    image_url="ลิงก์รูปภาพ หรือ GIF ที่ต้องการแสดงในห้องนี้โดยเฉพาะ"
)
@app_commands.choices(ticket_type=[
    app_commands.Choice(name="สั่งซื้อเงินเอ็ม (Buyer)", value="buyer"),
    app_commands.Choice(name="ขายเงินเอ็ม (Sell)", value="sell"),
    app_commands.Choice(name="สั่งของในเมือง (Preorder)", value="preorder")
])
async def slash_set_ticket_config(
    interaction: discord.Interaction,
    ticket_type: app_commands.Choice[str],
    title_text: str,
    description_text: str,
    image_url: str = None
):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

    guild_id = interaction.guild.id
    if guild_id not in ticket_configs:
        ticket_configs[guild_id] = {}

    ticket_configs[guild_id][ticket_type.value] = {
        'title': title_text,
        'description': description_text,
        'image': image_url
    }

    await interaction.response.send_message(
        f"✅ บันทึกการตั้งค่าหน้าตาห้อง Ticket หมวดหมู่ **{ticket_type.name}** เรียบร้อยแล้ว!",
        ephemeral=True
    )


# ----------------- ระบบ DM ส่งฟอร์มให้ลูกค้ากรอกรีวิว -----------------

async def send_feedback_panel(guild: discord.Guild, member_id: int):
    try:
        user = guild.get_member(member_id)
        if not user:
            user = await guild.fetch_member(member_id)
        if user:
            embed = discord.Embed(
                title="⭐ ให้คะแนนและเขียนรีวิวการบริการ",
                description="ห้อง Ticket ของคุณถูกปิดเรียบร้อยแล้ว\nกรุณากดปุ่มเลือกดาวด้านล่างเพื่อเขียนรีวิวส่งเข้าห้องรีวิวสาธารณะ:",
                color=discord.Color.gold()
            )
            view = FeedbackStarView(guild.id)
            await user.send(embed=embed, view=view)
    except Exception as e:
        print(f"Could not send DM feedback to user {member_id}: {e}")

class ReviewModal(discord.ui.Modal):
    def __init__(self, guild_id: int, stars: int):
        super().__init__(title=f"เขียนรีวิวบริการ ({'⭐' * stars})")
        self.guild_id = guild_id
        self.stars = stars

    review_text = discord.ui.TextInput(
        label="ความคิดเห็น / ข้อเสนอแนะ",
        style=discord.TextStyle.paragraph,
        placeholder="พิมพ์รีวิวบริการของคุณที่นี่...",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("🙏 ขอบคุณสำหรับรีวิวของคุณครับ! ระบบได้ส่งรีวิวไปยังห้องสาธารณะเรียบร้อยแล้ว", ephemeral=True)
        
        if self.guild_id in feedback_channels:
            ch_id = feedback_channels[self.guild_id]
            ch = interaction.client.get_channel(ch_id)
            if ch:
                star_str = "⭐" * self.stars
                embed = discord.Embed(
                    title="📝 รีวิวการให้บริการจากลูกค้า",
                    description=f"**ผู้รีวิว:** {interaction.user.mention}\n**คะแนน:** {star_str} ({self.stars}/5 ดาว)\n\n**รีวิว:**\n{self.review_text.value}",
                    color=discord.Color.gold()
                )
                await ch.send(embed=embed)

class FeedbackStarView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    async def disable_all_buttons(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="⭐ 1 ดาว", style=discord.ButtonStyle.danger, custom_id="fb_1")
    async def rating_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.disable_all_buttons(interaction)
        await interaction.response.send_modal(ReviewModal(self.guild_id, 1))

    @discord.ui.button(label="⭐⭐ 2 ดาว", style=discord.ButtonStyle.secondary, custom_id="fb_2")
    async def rating_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.disable_all_buttons(interaction)
        await interaction.response.send_modal(ReviewModal(self.guild_id, 2))

    @discord.ui.button(label="⭐⭐⭐ 3 ดาว", style=discord.ButtonStyle.secondary, custom_id="fb_3")
    async def rating_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.disable_all_buttons(interaction)
        await interaction.response.send_modal(ReviewModal(self.guild_id, 3))

    @discord.ui.button(label="⭐⭐⭐⭐ 4 ดาว", style=discord.ButtonStyle.success, custom_id="fb_4")
    async def rating_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.disable_all_buttons(interaction)
        await interaction.response.send_modal(ReviewModal(self.guild_id, 4))

    @discord.ui.button(label="⭐⭐⭐⭐⭐ 5 ดาว", style=discord.ButtonStyle.success, custom_id="fb_5")
    async def rating_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.disable_all_buttons(interaction)
        await interaction.response.send_modal(ReviewModal(self.guild_id, 5))


# ----------------- ระบบแอดมินเลือกข้อความรีวิวเพื่อเพิ่มรูปสลิป -----------------

class SlipModal(discord.ui.Modal, title="เพิ่ม/อัปเดตสลิปหลักฐาน"):
    def __init__(self, message: discord.Message):
        super().__init__()
        self.message = message
        if message.embeds and message.embeds[0].image:
            self.slip_link.default = message.embeds[0].image.url

    slip_link = discord.ui.TextInput(
        label="ลิงก์รูปสลิป (ที่ปิดชื่อแล้ว)",
        style=discord.TextStyle.short,
        placeholder="วางลิงก์รูปภาพ เช่น https://imgur.com/...",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            embed = self.message.embeds[0]
            if self.slip_link.value.startswith("http"):
                embed.set_image(url=self.slip_link.value.strip())
            
            await self.message.edit(embed=embed)
            await interaction.response.send_message("✅ อัปเดตรูปสลิปในรีวิวนี้เรียบร้อยแล้วครับ!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

class ReviewSelectDropdown(discord.ui.Select):
    def __init__(self, messages):
        options = []
        for msg in messages[:25]:
            content_snippet = msg.embeds[0].description[:90] if msg.embeds else "รีวิวบริการ"
            options.append(discord.SelectOption(
                label=content_snippet[:100], 
                value=str(msg.id), 
                description=f"ID: {msg.id}"
            ))
        super().__init__(placeholder="📌 เลือกโพสต์รีวิวที่ต้องการเพิ่มรูปสลิป", min_values=1, max_values=1, options=options)
        self.messages_map = {str(m.id): m for m in messages}

    async def callback(self, interaction: discord.Interaction):
        selected_msg_id = self.values[0]
        target_message = self.messages_map.get(selected_msg_id)
        if target_message:
            await interaction.response.send_modal(SlipModal(target_message))
        else:
            await interaction.response.send_message("❌ ไม่พบข้อความดังกล่าวแล้ว", ephemeral=True)

class ReviewSelectView(discord.ui.View):
    def __init__(self, messages):
        super().__init__(timeout=60)
        self.add_item(ReviewSelectDropdown(messages))

@bot.tree.command(name="add_slip", description="เลือกข้อความรีวิวเพื่อเพิ่มหรือแก้ไขรูปสลิป")
async def slash_add_slip(interaction: discord.Interaction):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

    guild_id = interaction.guild.id
    if guild_id not in feedback_channels:
        await interaction.response.send_message("❌ ยังไม่ได้ตั้งค่าห้องรีวิว กรุณาใช้คำสั่ง /set_feedback_channel ก่อน", ephemeral=True)
        return

    ch_id = feedback_channels[guild_id]
    channel = interaction.guild.get_channel(ch_id)
    if not channel:
        await interaction.response.send_message("❌ ไม่พบห้องรีวิวสาธารณะ", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    messages = []
    async for msg in channel.history(limit=25):
        if msg.author == bot.user and msg.embeds:
            messages.append(msg)

    if not messages:
        await interaction.followup.send("⚠️ ไม่พบโพสต์รีวิวในห้องรีวิว", ephemeral=True)
        return

    view = ReviewSelectView(messages)
    await interaction.followup.send("📋 เลือกโพสต์รีวิวที่ต้องการเพิ่มรูปสลิป:", view=view, ephemeral=True)


# ----------------- ปุ่มภายในห้อง Ticket (Close & Claim พร้อมกันในห้อง) -----------------

class InTicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_inline_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้", ephemeral=True)
            return

        ch = interaction.channel
        owner_id = int(ch.topic) if ch.topic and ch.topic.isdigit() else None
        
        await interaction.response.send_message("🗑️ กำลังปิดห้อง Ticket นี้...", ephemeral=True)
        try:
            await ch.delete(reason=f"Closed by {interaction.user}")
            if owner_id:
                asyncio.create_task(send_feedback_panel(interaction.guild, owner_id))
        except Exception as e:
            print(f"Failed to delete channel: {e}")

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="🙋‍♂️", custom_id="ticket_inline_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้", ephemeral=True)
            return

        await interaction.response.send_message(f"🙋‍♂️ แอดมิน **{interaction.user.mention}** เข้ามารับดูแลเคสนี้เรียบร้อยแล้วครับ!")


# ----------------- ระบบเปิด Ticket แบบเลือก 3 หมวดหมู่ (แก้ไขให้แสดง "โปรดเลือกหมวดหมู่") -----------------

class OpenTicketSelect(discord.ui.Select):
    def __init__(self, opt1_label, opt1_desc, opt2_label, opt2_desc, opt3_label, opt3_desc, role_to_tag1, role_to_tag2, role_to_tag3):
        options = [
            discord.SelectOption(label=opt1_label, description=opt1_desc, value="buyer", emoji="💵"),
            discord.SelectOption(label=opt2_label, description=opt2_desc, value="sell", emoji="💷"),
            discord.SelectOption(label=opt3_label, description=opt3_desc, value="preorder", emoji="📦")
        ]
        # ตั้งค่า Placeholder เริ่มต้นเป็น "📌 โปรดเลือกหมวดหมู่"
        super().__init__(placeholder="📌 โปรดเลือกหมวดหมู่", min_values=1, max_values=1, options=options)
        self.role_to_tag1 = role_to_tag1
        self.role_to_tag2 = role_to_tag2
        self.role_to_tag3 = role_to_tag3

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        guild_id = guild.id
        user = interaction.user

        if guild_id not in ticket_categories:
            await interaction.response.send_message("❌ แอดมินยังไม่ได้ตั้งค่าหมวดหมู่ Ticket (กรุณาใช้คำสั่ง /set_ticket_categories ก่อน)", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        choice = self.values[0]
        cats = ticket_categories[guild_id]
        
        category_id = cats.get(choice)
        category = guild.get_channel(category_id)
        if not category:
            await interaction.followup.send("❌ ไม่พบหมวดหมู่ห้องในระบบ กรุณาให้แอดมินตั้งค่าใหม่", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }

        if guild_id in ticket_roles:
            admin_role = guild.get_role(ticket_roles[guild_id])
            if admin_role:
                overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel_count = len(category.text_channels) + 1
        channel_name = f"{choice}-{channel_count}"

        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=str(user.id),
                reason=f"Ticket opened by {user}"
            )

            cfg = ticket_configs.get(guild_id, {}).get(choice, {})
            title_val = cfg.get('title', f"THNK FOR {choice.upper()}")
            desc_val = cfg.get('description', f"สวัสดีคุณ {user.mention} กรุณาแจ้งรายละเอียดหรือส่งสลิปได้เลยครับ!")
            img_val = cfg.get('image', None)

            embed = discord.Embed(
                title=title_val,
                description=desc_val,
                color=discord.Color.dark_theme()
            )
            if img_val:
                embed.set_image(url=img_val)

            tag_mentions = [user.mention]
            for r in [self.role_to_tag1, self.role_to_tag2, self.role_to_tag3]:
                if r:
                    tag_mentions.append(r.mention)

            ping_content = " ".join(tag_mentions)

            view = InTicketControlView()
            await ticket_channel.send(content=ping_content, embed=embed, view=view)
            await interaction.followup.send(f"✅ เปิดห้อง Ticket ให้คุณแล้วที่ห้อง: {ticket_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาดในการสร้างห้อง: {e}", ephemeral=True)

class OpenTicketView(discord.ui.View):
    def __init__(self, opt1_label, opt1_desc, opt2_label, opt2_desc, opt3_label, opt3_desc, role_to_tag1, role_to_tag2, role_to_tag3):
        super().__init__(timeout=None)
        self.add_item(OpenTicketSelect(opt1_label, opt1_desc, opt2_label, opt2_desc, opt3_label, opt3_desc, role_to_tag1, role_to_tag2, role_to_tag3))

@bot.tree.command(name="setup_open_ticket", description="ส่งแผงเลือกหมวดหมู่เปิด Ticket พร้อมตั้งค่าแท็กยศ")
@app_commands.describe(
    channel="เลือกห้องแชทที่จะส่งแผงนี้", 
    image_url="ลิงก์รูปภาพหรือ GIF สำหรับแผงเลือก (ด้านนอก)",
    tag_role_1="เลือกยศที่ 1 ที่ต้องการให้แท็กในห้อง Ticket",
    tag_role_2="เลือกยศที่ 2 ที่ต้องการให้แท็กในห้อง Ticket",
    tag_role_3="เลือกยศที่ 3 ที่ต้องการให้แท็กในห้อง Ticket",
    title_text="หัวข้อหลักของ Embed (ด้านนอก)",
    description_text="รายละเอียดใน Embed (ด้านนอก)",
    opt1_label="ชื่อตัวเลือกที่ 1",
    opt1_desc="คำอธิบายตัวเลือกที่ 1",
    opt2_label="ชื่อตัวเลือกที่ 2",
    opt2_desc="คำอธิบายตัวเลือกที่ 2",
    opt3_label="ชื่อตัวเลือกที่ 3",
    opt3_desc="คำอธิบายตัวเลือกที่ 3"
)
async def slash_setup_open_ticket(
    interaction: discord.Interaction, 
    channel: discord.TextChannel, 
    image_url: str = None,
    tag_role_1: discord.Role = None,
    tag_role_2: discord.Role = None,
    tag_role_3: discord.Role = None,
    title_text: str = "• ˚  ★  // open ticket  • ˚ ‧  ★",
    description_text: str = "เลือกสินค้าด้านล่าง",
    opt1_label: str = "Buyer-Money",
    opt1_desc: str = "สั่งซื้อเงินเอ็ม",
    opt2_label: str = "Sell-money",
    opt2_desc: str = "ขายเงินเอ็ม",
    opt3_label: str = "Preorder",
    opt3_desc: str = "สั่งของในเมือง"
):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return

    embed = discord.Embed(
        title=title_text,
        description=description_text,
        color=discord.Color.dark_purple()
    )
    if image_url:
        embed.set_image(url=image_url)

    view = OpenTicketView(opt1_label, opt1_desc, opt2_label, opt2_desc, opt3_label, opt3_desc, tag_role_1, tag_role_2, tag_role_3)
    await channel.send(embed=embed, view=view)
    await interaction.response.send_message(f"✅ ส่งแผงเลือกเปิด Ticket ไปที่ห้อง {channel.mention} เรียบร้อยแล้วครับ!", ephemeral=True)


# ----------------- ระบบจัดการห้อง Ticket (ปิดห้องแผงแอดมินรวม) -----------------

class SingleTicketSelect(discord.ui.Select):
    def __init__(self, channels):
        options = [discord.SelectOption(label=ch.name[:100], value=str(ch.id)) for ch in channels[:25]]
        super().__init__(placeholder="📌 เลือกห้อง Ticket ที่ต้องการปิด", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        ch = interaction.guild.get_channel(int(self.values[0]))
        if ch:
            try:
                name = ch.name
                owner_id = int(ch.topic) if ch.topic and ch.topic.isdigit() else None

                await ch.delete(reason=f"Closed by {interaction.user}")
                await interaction.followup.send(f"🗑️ ปิดห้อง Ticket **{name}** เรียบร้อยแล้วครับ!", ephemeral=True)
                
                if owner_id:
                    asyncio.create_task(send_feedback_panel(interaction.guild, owner_id))
            except Exception as e:
                await interaction.followup.send(f"❌ ไม่สามารถปิดห้องนี้ได้: {e}", ephemeral=True)
        else:
            await interaction.followup.send("❌ ไม่พบห้องดังกล่าวแล้ว", ephemeral=True)

class SingleTicketView(discord.ui.View):
    def __init__(self, channels):
        super().__init__(timeout=120)
        self.add_item(SingleTicketSelect(channels))

class MultiTicketSelect(discord.ui.Select):
    def __init__(self, channels):
        options = [discord.SelectOption(label=ch.name[:100], value=str(ch.id)) for ch in channels[:25]]
        super().__init__(placeholder="📌 เลือกห้อง Ticket ที่ต้องการปิด", min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        closed_count = 0
        for channel_id in self.values:
            ch = interaction.guild.get_channel(int(channel_id))
            if ch:
                try:
                    owner_id = int(ch.topic) if ch.topic and ch.topic.isdigit() else None
                    await ch.delete(reason=f"Multi-closed by {interaction.user}")
                    closed_count += 1
                    if owner_id:
                        asyncio.create_task(send_feedback_panel(interaction.guild, owner_id))
                    await asyncio.sleep(0.4)
                except Exception as e:
                    print(f"Failed: {e}")
        await interaction.followup.send(f"✅ ปิดห้อง Ticket สำเร็จทั้งหมด **{closed_count}** ห้องแล้วครับ!", ephemeral=True)

class MultiTicketView(discord.ui.View):
    def __init__(self, channels):
        super().__init__(timeout=120)
        self.add_item(MultiTicketSelect(channels))

class TicketManageView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🗑️ ปิดห้องเดียว", style=discord.ButtonStyle.primary, custom_id="persistent_btn_single")
    async def btn_single(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้", ephemeral=True)
            return
        channels = [ch for ch in interaction.guild.text_channels if any(k in ch.name.lower() for k in ["buyer", "sell", "preorder", "ticket"])]
        if not channels:
            await interaction.response.send_message("⚠️ ไม่พบห้อง Ticket ในขณะนี้ครับ", ephemeral=True)
            return
        await interaction.response.send_message("📋 กรุณาเลือกห้อง Ticket ที่ต้องการปิด:", view=SingleTicketView(channels), ephemeral=True)

    @discord.ui.button(label="☑️ เลือกปิดหลายห้อง", style=discord.ButtonStyle.success, custom_id="persistent_btn_multi")
    async def btn_multi(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้", ephemeral=True)
            return
        channels = [ch for ch in interaction.guild.text_channels if any(k in ch.name.lower() for k in ["buyer", "sell", "preorder", "ticket"])]
        if not channels:
            await interaction.response.send_message("⚠️ ไม่พบห้อง Ticket ในขณะนี้ครับ", ephemeral=True)
            return
        await interaction.response.send_message("📋 กรุณาเลือกห้อง Ticket ที่ต้องการปิด:", view=MultiTicketView(channels), ephemeral=True)

    @discord.ui.button(label="🚨 ปิดห้องทั้งหมด", style=discord.ButtonStyle.danger, custom_id="persistent_btn_all")
    async def btn_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator and not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("❌ ปุ่มปิดห้องทั้งหมด ต้องใช้สิทธิ์ผู้ดูแลระบบเท่านั้น", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        channels_to_delete = [ch for ch in interaction.guild.text_channels if any(k in ch.name.lower() for k in ["buyer", "sell", "preorder", "ticket"])]
        if not channels_to_delete:
            await interaction.followup.send("⚠️ ไม่พบห้อง Ticket ที่ต้องปิด", ephemeral=True)
            return
        closed_count = 0
        for ch in channels_to_delete:
            try:
                owner_id = int(ch.topic) if ch.topic and ch.topic.isdigit() else None
                await ch.delete(reason=f"Bulk closed by {interaction.user}")
                closed_count += 1
                if owner_id:
                    asyncio.create_task(send_feedback_panel(interaction.guild, owner_id))
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"Failed: {e}")
        await interaction.followup.send(f"✅ ปิดห้อง Ticket ทั้งหมดสำเร็จ **{closed_count}** ห้องแล้วครับ!", ephemeral=True)

@bot.tree.command(name="set_ticket_role", description="กำหนดว่ายศไหนมีสิทธิ์ใช้คำสั่งและปุ่มจัดการต่างๆ")
@app_commands.describe(role="เลือกยศที่ต้องการให้มีสิทธิ์")
async def slash_set_ticket_role(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ เฉพาะแอดมินเท่านั้นที่ตั้งค่าคำสั่งนี้ได้", ephemeral=True)
        return
    ticket_roles[interaction.guild.id] = role.id
    await interaction.response.send_message(f"✅ ตั้งค่าสำเร็จ! ผู้ที่มียศ **{role.name}** จะสามารถใช้คำสั่งและจัดการระบบต่างๆ ได้แล้ว", ephemeral=True)

@bot.tree.command(name="setup_ticket", description="ส่งแผงควบคุมระบบปิด Ticket ไปยังห้องแชท")
@app_commands.describe(channel="เลือกห้องแชทที่ต้องการส่งแผงควบคุม")
async def slash_setup_ticket(interaction: discord.Interaction, channel: discord.TextChannel):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (ต้องเป็นแอดมินหรือมียศที่ได้รับอนุญาตเท่านั้น)", ephemeral=True)
        return
    embed = discord.Embed(
        title="🎫 ระบบจัดการห้อง Ticket",
        description="เลือกปุ่มด้านล่างเพื่อจัดการปิดห้อง Ticket:",
        color=discord.Color.blurple()
    )
    window_view = TicketManageView()
    await channel.send(embed=embed, view=window_view)
    await interaction.response.send_message(f"✅ ส่งแผงควบคุมไปที่ห้อง {channel.mention} เรียบร้อยแล้ว!", ephemeral=True)


keep_alive()
bot.run(os.environ.get("DISCORD_TOKEN"))
