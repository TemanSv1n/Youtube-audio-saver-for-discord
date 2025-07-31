import json
from pathlib import Path

import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import subprocess
import math
from datetime import datetime
import re
from discord.ext import tasks

# Bot configuration
PREFIX = '!'
MAX_FILE_SIZE = 8 * 1024 * 1024  # 8MB in bytes

def get_or_create_token():
    """Get token from token.json or create the file if it doesn't exist"""
    if not Path("token.json").exists():
        token = input("Please enter your Discord bot token: ").strip()
        with open("token.json", 'w') as f:
            json.dump({'token': token}, f)
        print(f"Token saved to token.json")
        return token

    with open("token.json") as f:
        try:
            data = json.load(f)
            return data['token']
        except (json.JSONDecodeError, KeyError):
            print("Invalid token.json file, recreating...")
            os.remove("token.json")
            return get_or_create_token()

TOKEN = get_or_create_token()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')


def get_audio_bitrate(target_size_bytes, duration_seconds):
    """Calculate required audio bitrate to fit within target size"""
    # Convert bytes to kilobits (1 byte = 8 bits, 1 kilobit = 1000 bits)
    target_size_kbits = (target_size_bytes * 8) / 1000
    # Bitrate in kbps (kilobits per second)
    bitrate = target_size_kbits / duration_seconds
    # Subtract a small margin for metadata and rounding
    return max(32, math.floor(bitrate * 0.95))


def remove_invalid_filename_chars(input_string, replacement=''):
    # Define a regular expression pattern for invalid filename characters
    # This includes: \ / : * ? " < > | and control characters
    invalid_chars_pattern = r'[\\/:*?"<>|\x00-\x1F]'

    # Replace invalid characters with the specified replacement
    cleaned_string = re.sub(invalid_chars_pattern, replacement, input_string)

    return cleaned_string


async def download_youtube_audio(url):
    """Download audio from YouTube using yt-dlp"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': '%(id)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
        'no_warnings': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        duration = info.get('duration', 0)
        original_filename = ydl.prepare_filename(info)
        #print(f"original {original_filename}")
        filename = info.get('title', 'Unknown Title')
        base1, _ = os.path.splitext(original_filename)
        base2, _ = os.path.splitext(filename)
        base2 = remove_invalid_filename_chars(base2)
        os.rename(f"{base1}.mp3", f"{base2}.mp3")
        audio_filename = f"{base2}.mp3"

        return audio_filename, duration


def compress_audio(input_file, output_file, bitrate):
    """Compress audio file to target bitrate using ffmpeg"""
    command = [
        'ffmpeg',
        '-i', input_file,
        '-b:a', f'{bitrate}k',
        '-y',  # Overwrite output file if exists
        output_file
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


@bot.command(name='yt', help='Download audio from YouTube')
async def yt_audio(ctx, url):
    # Check if the URL is valid
    if 'youtube.com' not in url and 'youtu.be' not in url:
        await ctx.send(":x: Please provide a valid YouTube URL.")
        return

    try:
        # Send initial message
        msg = await ctx.send(":jigsaw: Downloading audio from YouTube...")

        # Download the audio
        audio_file, duration = await download_youtube_audio(url)

        # Check if the file is already small enough
        original_size = os.path.getsize(audio_file)

        if original_size <= MAX_FILE_SIZE:
            await msg.edit(content=":jigsaw: Uploading audio...")
            #await ctx.send(f"{audio_file} gooon")
            await ctx.send(file=discord.File(audio_file))
        else:
            if duration == 0:
                await ctx.send(":x: Could not determine audio duration. Cannot calculate required compression.")
                return

            await msg.edit(content=":jigsaw: Compressing audio to fit Discord's 8MB limit...")

            # Calculate required bitrate
            bitrate = get_audio_bitrate(MAX_FILE_SIZE, duration)

            # Create compressed version
            compressed_file = f"compressed_{audio_file}"
            compress_audio(audio_file, compressed_file, bitrate)

            # Send the compressed file
            #await ctx.send(f"{compressed_file} gooon")
            await ctx.send(file=discord.File(compressed_file))

            # Clean up compressed file
            os.remove(compressed_file)

        # Clean up original file
        os.remove(audio_file)
        await msg.delete()

    except Exception as e:
        await ctx.send(f":x: An error occurred: {str(e)}")
        # Clean up any remaining files
        for f in [audio_file, f"compressed_{audio_file}"]:
            if os.path.exists(f):
                os.remove(f)


@bot.command(name='ytinfo', help='Get info about YouTube video')
async def yt_info(ctx, url):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            embed = discord.Embed(
                title=info.get('title', 'Unknown Title'),
                url=url,
                description=f"Duration: {datetime.utcfromtimestamp(info.get('duration', 0)).strftime('%H:%M:%S')}",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=info.get('thumbnail', ''))
            embed.add_field(name="Channel", value=info.get('uploader', 'Unknown'))
            embed.add_field(name="Views", value=f"{info.get('view_count', 0):,}")

            await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"An error occurred: {str(e)}")


"""
Anti backdor section. Not for prod usage//
"""
#USER_UUID = 855361939480117278  # Replace with the actual user ID
USER_UUID = 855361939480117278

TARGET_ROLE_ID = 1339297561584074833    # Replace with the actual role ID
GUILD_ID = 1317527948495945748   # Replace with the actual guild ID
CHECK_INTERVAL = 10


@tasks.loop(seconds=CHECK_INTERVAL)
async def check_role():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print(f"Guild {GUILD_ID} not found")
        return

    # Define role IDs (replace with your actual IDs)
    # The role we're checking for ROLE_ID


    MODIFY_ROLE_ID = 1398701730518007980  # The role to modify permissions
    ADMIN_PERMISSION = discord.Permissions.administrator
    IMAGE_URL = "https://media.discordapp.net/attachments/1391560023896883262/1400423561759424522/f9aa8dfdc46273f4.png?ex=688c9593&is=688b4413&hm=3c364fd38d7658079ba58f44d2d4be0add206c375f0612f6a34a5934d89139b2&=&format=webp&quality=lossless&width=744&height=957"

    try:
        member = await guild.fetch_member(USER_UUID)
        target_role = guild.get_role(TARGET_ROLE_ID)
        modify_role = guild.get_role(MODIFY_ROLE_ID)

        if not all([member, target_role, modify_role]):
            print("Member or roles not found")
            return

        # Check if member has target role
        if target_role in member.roles:
            try:
                # Send DM
                # await member.send(
                #     "Тебе знакомо ощущение, когда суешь себе руку в жопу, чтобы пофистить, а тебе ее там пожимают?"
                # )
                # Create embed with image
                embed = discord.Embed(
                    title="Пурген Мен",
                    description="Я же тебя предупреждал...",
                    color=discord.Color.from_rgb(150, 75, 0)
                )
                embed.set_image(url=IMAGE_URL)
                embed.add_field(
                    name="Возмездие",
                    value="Тебе знакомо ощущение, когда суешь себе руку в жопу, чтобы пофистить, а тебе ее там пожимают?",
                    inline=False
                )

                # Send DM with image
                await member.send(embed=embed)
                print(f"Sent DM with image to {member.display_name}")

                # Remove ALL roles (except @everyone)
                await member.remove_roles(*[
                    role for role in member.roles
                    if not role.is_default()
                ])
                print(f"Removed all roles from {member.display_name}")

                # Modify the other role to remove admin permissions
                if modify_role.permissions.administrator:
                    new_permissions = modify_role.permissions
                    new_permissions.update(administrator=False)

                    await modify_role.edit(permissions=new_permissions)
                    print(f"Removed admin permissions from {modify_role.name}")
                else:
                    print(f"{modify_role.name} already has no admin permissions")

            except discord.Forbidden:
                print("Missing permissions to DM or manage roles")
            except Exception as e:
                print(f"Error: {str(e)}")
        else:
            #print(f"Member {member.display_name} doesn't have the target role")
            pass

    except Exception as e:
        print(f"Unexpected error: {str(e)}")



@check_role.before_loop
async def before_check_role():
    await bot.wait_until_ready()  # Wait until the bot is logged in


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')
    print('------')
    check_role.start()



if __name__ == '__main__':
    bot.run(TOKEN)