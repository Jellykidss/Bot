import discord
from discord.ext import commands
from keep_alive import keep_alive

# ตั้งค่า Intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

# สร้าง Bot Instance
bot = commands.Bot(command_prefix="!", intents=intents)

# กำหนด ID ของห้องเสียง
CHANNEL_ID = 1546510895813886002

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("Bot is ready and online!")
    
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        if not discord.utils.get(bot.voice_clients, guild=channel.guild):
            try:
                await channel.connect()
                print(f"เชื่อมต่อเข้าห้อง **{channel.name}** เรียบร้อยแล้ว!")
            except Exception as e:
                print(f"เกิดข้อผิดพลาดในการเข้าห้อง: {e}")
    else:
        print("ไม่พบห้องเสียง กรุณาตรวจสอบ ID อีกครั้ง")

# คำสั่ง join
@bot.command(name="join")
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        if ctx.voice_client is not None:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await ctx.send(f"เชื่อมต่อเข้าห้อง **{channel.name}** เรียบร้อยแล้ว!")
    else:
        await ctx.send("กรุณาเข้าห้องเสียงก่อนใช้คำสั่งนี้!")

# คำสั่ง leave
@bot.command(name="leave")
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("ออกจากห้องเสียงแล้ว")
    else:
        await ctx.send("บอทไม่ได้อยู่ในห้องเสียงในขณะนี้")

# สั่งรันเว็บเซิร์ฟเวอร์รักษาสถานะออนไลน์
keep_alive()

# รันบอทด้วย Token ของคุณ
bot.run("MTU0NjUwNDc1MDYzODU2MzM5MQ.Ggwp9t.D9UuGXjqowtYVf2ERoJkPoavbM_Gw9KCN0_AnY")