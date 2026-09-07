import os
import discord
from discord import app_commands
from discord.ext import commands
from keep_alive import keep_alive

# กำหนด Intent ของบอท
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# กำหนดไอดีห้องเสียงเป้าหมายที่คุณต้องการให้บอทเข้าอัตโนมัติ
TARGET_CHANNEL_ID = 1546510895813886002

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")
    # ซิงค์ Slash Commands กับ Discord
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # เชื่อมต่อเข้าห้องเสียงเป้าหมายอัตโนมัติเมื่อบอทออนไลน์
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel and isinstance(channel, discord.VoiceChannel):
        if not discord.utils.get(bot.voice_clients, guild=channel.guild):
            try:
                await channel.connect()
                print(f"Connected to voice channel: {channel.name}")
            except Exception as e:
                print(f"เกิดข้อผิดพลาดในการเชื่อมต่อเสียง: {e}")

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
        await voice_client.disconnect()
        await interaction.response.send_message("ออกจากห้องเสียงเรียบร้อยแล้วครับ!", ephemeral=True)
    else:
        await interaction.response.send_message("บอทไม่ได้อยู่ในห้องเสียงในขณะนี้ครับ!", ephemeral=True)

# รันระบบ Keep Alive สำหรับ Render
keep_alive()

# ใส่ Token ของบอทคุณตรงนี้
bot.run(os.environ.get("DISCORD_TOKEN"))
