import os
import asyncio
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
    
    # ระบบพยายามเชื่อมต่อเข้าห้องเสียงอัตโนมัติจนกว่าจะสำเร็จ
    while True:
        try:
            channel = await bot.fetch_channel(CHANNEL_ID)
            if channel:
                # ตรวจสอบว่าบอทอยู่ในห้องเสียงนี้หรือยัง
                voice_client = discord.utils.get(bot.voice_clients, guild=channel.guild)
                if voice_client and voice_client.is_connected():
                    if voice_client.channel.id == channel.id:
                        print(f"บอทอยู่ในห้อง **{channel.name}** เรียบร้อยแล้ว")
                        break
                    else:
                        await voice_client.move_to(channel)
                        print(f"ย้ายบอทมายังห้อง **{channel.name}** เรียบร้อยแล้ว")
                        break
                else:
                    await channel.connect()
                    print(f"เชื่อมต่อเข้าห้อง **{channel.name}** เรียบร้อยแล้ว!")
                    break
        except Exception as e:
            print(f"กำลังลองเชื่อมต่อเข้าห้องเสียงใหม่... (ข้อผิดพลาด: {e})")
        
        # รอ 5 วินาทีก่อนลองใหม่หากยังไม่สำเร็จ
        await asyncio.sleep(5)

# คำสั่งเรียกบอทเข้าห้องเสียง (พิมพ์ !join ในแชท)
@bot.command(name="join")
async def join(ctx):
    try:
        channel = await bot.fetch_channel(CHANNEL_ID)
        if channel:
            if ctx.voice_client is not None:
                await ctx.voice_client.move_to(channel)
            else:
                await channel.connect()
            await ctx.send(f"ดึงบอทเข้าห้อง **{channel.name}** เรียบร้อยแล้วครับ!")
        else:
            await ctx.send("ไม่พบห้องเสียงที่กำหนดไว้")
    except Exception as e:
        await ctx.send(f"เกิดข้อผิดพลาด: {e}")

# คำสั่งออกห้องเสียง (พิมพ์ !leave ในแชท)
@bot.command(name="leave")
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("ออกจากห้องเสียงแล้ว")
    else:
        await ctx.send("บอทไม่ได้อยู่ในห้องเสียงในขณะนี้")

# สั่งรันเว็บเซิร์ฟเวอร์รักษาสถานะออนไลน์
keep_alive()

# รันบอทด้วย Environment Variable
bot.run(os.getenv("DISCORD_TOKEN"))
