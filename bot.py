import discord
from discord.ext import commands
from discord import app_commands
from supabase import create_client, Client
import datetime
import asyncio
import os

# ===================== BOT SETUP =====================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ===================== SUPABASE SETUP =====================
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ===================== LOGGING FUNCTION =====================
def add_log(guild_id: str, action: str, target_user: str, role_name: str, performed_by: str, reason: str, notes: str = ""):
    try:
        print("LOG: inserting audit log")

        result = supabase.table("audit_logs").insert({
            "guild_id": str(guild_id),
            "action": action,
            "target_user": str(target_user),
            "role_name": str(role_name),
            "performed_by": str(performed_by),
            "reason": reason,
            "notes": notes,
            "is_voided": False
        }).execute()

        return result.data[0]["id"] if result.data else 0

    except Exception as e:
        print(f"LOG ERROR: {e}")
        return 0

# ===================== BOT READY =====================
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Slash commands synced: {len(synced)}")
    except Exception as e:
        print(f"Sync error: {e}")

# ===================== PROMOTE =====================
@bot.tree.command(name="promote")
async def promote(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str):
    await member.add_roles(role)

    add_log(
        interaction.guild.id,
        "promote",
        str(member.id),
        role.name,
        str(interaction.user.id),
        reason,
        ""
    )

    await interaction.response.send_message(f"{member.mention} promoted to {role.name}")

# ===================== DEMOTE =====================
@bot.tree.command(name="demote")
async def demote(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str):
    await member.remove_roles(role)

    add_log(
        interaction.guild.id,
        "demote",
        str(member.id),
        role.name,
        str(interaction.user.id),
        reason,
        ""
    )

    await interaction.response.send_message(f"{member.mention} demoted from {role.name}")

# ===================== KICK =====================
@bot.tree.command(name="kick")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str):
    await member.kick(reason=reason)

    add_log(
        interaction.guild.id,
        "kick",
        str(member.id),
        "N/A",
        str(interaction.user.id),
        reason,
        ""
    )

    await interaction.response.send_message(f"{member.mention} was kicked")

# ===================== WARN =====================
@bot.tree.command(name="warn")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):

    add_log(
        interaction.guild.id,
        "warn",
        str(member.id),
        "N/A",
        str(interaction.user.id),
        reason,
        ""
    )

    await interaction.response.send_message(f"{member.mention} warned")

# ===================== MUTE =====================
@bot.tree.command(name="mute")
async def mute(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str):
    await member.add_roles(role)

    add_log(
        interaction.guild.id,
        "mute",
        str(member.id),
        role.name,
        str(interaction.user.id),
        reason,
        ""
    )

    await interaction.response.send_message(f"{member.mention} muted")

# ===================== UNMUTE =====================
@bot.tree.command(name="unmute")
async def unmute(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str):
    await member.remove_roles(role)

    add_log(
        interaction.guild.id,
        "unmute",
        str(member.id),
        role.name,
        str(interaction.user.id),
        reason,
        ""
    )

    await interaction.response.send_message(f"{member.mention} unmuted")

# ===================== HISTORY =====================
@bot.tree.command(name="history")
async def history(interaction: discord.Interaction, member: discord.Member):
    one_day_ago = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).isoformat()

    response = supabase.table("audit_logs") \
        .select("*") \
        .eq("target_user", str(member.id)) \
        .gte("timestamp", one_day_ago) \
        .execute()

    logs = response.data

    if not logs:
        await interaction.response.send_message("No logs found.")
        return

    msg = ""
    for log in logs:
        msg += f"{log['action']} | {log['reason']} | {log['timestamp']}\n"

    await interaction.response.send_message(msg[:2000])

# ===================== RUN BOT =====================
bot.run(os.getenv("DISCORD_TOKEN"))
