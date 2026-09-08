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
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
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
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
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
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ คำสั่งนี้ต้องใช้สิทธิ์ผู้ดูแลระบบเท่านั้น", ephemeral=True)
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


# ----------------- ระบบ Ticket & รีวิวความพึงพอใจ -----------------

def has_ticket_permission(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_channels:
        return True
    guild_id = interaction.guild.id
    if guild_id in ticket_roles:
        role = interaction.guild.get_role(ticket_roles[guild_id])
        if role and role in interaction.user.roles:
            return True
    return False

@bot.tree.command(name="set_feedback_channel", description="กำหนดห้องรีวิวสาธารณะ")
@app_commands.describe(channel="เลือกห้องแชทที่จะให้แสดงรีวิว")
async def slash_set_feedback_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ เฉพาะแอดมินเท่านั้นที่ตั้งค่าได้", ephemeral=True)
        return
    feedback_channels[interaction.guild.id] = channel.id
    await interaction.response.send_message(f"✅ ตั้งค่าห้องรีวิวสำเร็จที่ห้อง {channel.mention}", ephemeral=True)

async def send_feedback_panel(guild: discord.guild, member_id: int):
    try:
        user = guild.get_member(member_id)
        if not user:
            user = await guild.fetch_member(member_id)
        if user:
            embed = discord.Embed(
                title="⭐ ให้คะแนนและเขียนรีวิวการบริการ",
                description="ห้อง Ticket ของคุณถูกปิดเรียบร้อยแล้ว\nกรุณากดปุ่มเลือกดาวด้านล่างเพื่อเขียนรีวิวการบริการครับ:",
                color=discord.Color.gold()
            )
            view = FeedbackStarView(guild.id)
            await user.send(embed=embed, view=view)
    except Exception as e:
        print(f"Could not send DM feedback: {e}")

class ReviewModal(discord.ui.Modal):
    def __init__(self, guild_id: int, stars: int):
        super().__init__(title=f"เขียนรีวิว ({'⭐' * stars})")
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
        await interaction.response.send_message("🙏 ขอบคุณสำหรับคะแนนและรีวิวของคุณครับ!", ephemeral=True)
        
        # ส่งรีวิวตรงไปที่ห้องรีวิวสาธารณะทันที!
        if self.guild_id in feedback_channels:
            channel_id = feedback_channels[self.guild_id]
            channel = interaction.client.get_channel(channel_id)
            if channel:
                star_str = "⭐" * self.stars
                embed = discord.Embed(
                    title="📝 รีวิวการให้บริการจากลูกค้า",
                    description=f"**ผู้รีวิว:** {interaction.user.mention}\n**คะแนน:** {star_str} ({self.stars}/5 ดาว)\n\n**รีวิว:**\n{self.review_text.value}",
                    color=discord.Color.gold()
                )
                embed.set_footer(text=f"User ID: {interaction.user.id} | ยังไม่แนบสลิป", icon_url=interaction.user.display_avatar.url)
                
                # ส่งพร้อมปุ่มให้แอดมินกดใส่รูปทีหลังได้ทันทีใต้ข้อความนั้นๆ
                view = AdminAddSlipView()
                await channel.send(embed=embed, view=view)

class FeedbackStarView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="⭐ 1 ดาว", style=discord.ButtonStyle.danger, custom_id="fb_1")
    async def rating_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewModal(self.guild_id, 1))

    @discord.ui.button(label="⭐⭐ 2 ดาว", style=discord.ButtonStyle.secondary, custom_id="fb_2")
    async def rating_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewModal(self.guild_id, 2))

    @discord.ui.button(label="⭐⭐⭐ 3 ดาว", style=discord.ButtonStyle.secondary, custom_id="fb_3")
    async def rating_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewModal(self.guild_id, 3))

    @discord.ui.button(label="⭐⭐⭐⭐ 4 ดาว", style=discord.ButtonStyle.success, custom_id="fb_4")
    async def rating_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewModal(self.guild_id, 4))

    @discord.ui.button(label="⭐⭐⭐⭐⭐ 5 ดาว", style=discord.ButtonStyle.success, custom_id="fb_5")
    async def rating_5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReviewModal(self.guild_id, 5))


# ----------------- ระบบแอดมินคลิกเพิ่มรูปสลิปที่ข้อความรีวิวโดยตรง -----------------

class EditSlipModal(discord.ui.Modal, title="เพิ่ม/แก้ไขรูปสลิปในรีวิว"):
    def __init__(self, message: discord.Message):
        super().__init__()
        self.message = message

    slip_link = discord.ui.TextInput(
        label="ลิงก์รูปสลิป (ที่ปิดชื่อแล้ว)",
        style=discord.TextStyle.short,
        placeholder="วางลิงก์รูปภาพ เช่น https://imgur.com/...",
        required=True,
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
            return

        try:
            link = self.slip_link.value.strip()
            if not (link.startswith("http://") or link.startswith("https://")):
                await interaction.response.send_message("❌ ลิงก์รูปภาพไม่ถูกต้อง ต้องเริ่มต้นด้วย http:// หรือ https://", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            if self.message.embeds:
                embed = self.message.embeds[0]
                embed.set_image(url=link)
                # อัปเดต footer แจ้งว่ามีสลิปแล้ว
                current_footer = embed.footer.text if embed.footer else ""
                base_footer = current_footer.split(" | ")[0] if " | " in current_footer else current_footer
                embed.set_footer(text=f"{base_footer} | ✅ แนบสลิปแล้วโดย {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
                
                # อัปเดตข้อความเดิมทันทีโดยไม่ต้องเปลี่ยนห้อง
                await self.message.edit(embed=embed)

            await interaction.followup.send("✅ อัปเดตใส่รูปสลิปในรีวิวนี้เรียบร้อยแล้วครับ!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)

class AdminAddSlipView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🖼️ เพิ่ม/แก้ไขรูปสลิป", style=discord.ButtonStyle.success, custom_id="admin_edit_slip_btn")
    async def edit_slip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์กดปุ่มนี้", ephemeral=True)
            return
        await interaction.response.send_modal(EditSlipModal(interaction.message))

# รองรับคลิกขวาที่ข้อความเพื่อเพิ่มรูปสลิปได้ด้วยเช่นกัน
@bot.tree.context_menu(name="เพิ่มรูปสลิปรีวิว")
async def context_add_slip(interaction: discord.Interaction, message: discord.Message):
    if not has_ticket_permission(interaction):
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
        return
    await interaction.response.send_modal(EditSlipModal(message))


# ----------------- ระบบจัดการห้อง Ticket -----------------

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
                    await send_feedback_panel(interaction.guild, owner_id)
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
        channels = [ch for ch in interaction.guild.text_channels if "ticket" in ch.name.lower() or "تيكيت" in ch.name.lower()]
        if not channels:
            await interaction.response.send_message("⚠️ ไม่พบห้อง Ticket ในขณะนี้ครับ", ephemeral=True)
            return
        await interaction.response.send_message("📋 กรุณาเลือกห้อง Ticket ที่ต้องการปิด (1 ห้อง):", view=SingleTicketView(channels), ephemeral=True)

    @discord.ui.button(label="☑️ เลือกปิดหลายห้อง", style=discord.ButtonStyle.success, custom_id="persistent_btn_multi")
    async def btn_multi(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_ticket_permission(interaction):
            await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานปุ่มนี้", ephemeral=True)
            return
        channels = [ch for ch in interaction.guild.text_channels if "ticket" in ch.name.lower() or "تيكيت" in ch.name.lower()]
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
        channels_to_delete = [ch for ch in interaction.guild.text_channels if "ticket" in ch.name.lower() or "تيكيت" in ch.name.lower()]
        if not channels_to_delete:
            await interaction.followup.send("⚠️ ไม่พบห้อง Ticket ที่ต้องปิด", ephemeral=TaskPoolChannel) # type: ignore
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

@bot.tree.command(name="set_ticket_role", description="กำหนดว่ายศไหนมีสิทธิ์ใช้ปุ่มจัดการ Ticket")
@app_commands.describe(role="เลือกยศที่ต้องการให้มีสิทธิ์")
async def slash_set_ticket_role(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ เฉพาะแอดมินเท่านั้นที่ตั้งค่าได้", ephemeral=True)
        return
    ticket_roles[interaction.guild.id] = role.id
    await interaction.response.send_message(f"✅ ตั้งค่าสำเร็จ! ผู้ที่มียศ **{role.name}** จะสามารถใช้ปุ่มจัดการ Ticket ได้แล้ว", ephemeral=True)

@bot.tree.command(name="setup_ticket", description="ส่งแผงควบคุมระบบ Ticket ไปยังห้องแชท")
@app_commands.describe(channel="เลือกห้องแชทที่ต้องการส่งแผงควบคุม")
async def slash_setup_ticket(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้", ephemeral=True)
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
