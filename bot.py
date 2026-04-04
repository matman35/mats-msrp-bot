import discord
from discord import app_commands
from discord.ext import commands
import os
import requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

# ──────────────────────────────────────────
# WEBHOOK LOGGING (ADDED)
# ──────────────────────────────────────────

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

def log_webhook(message: str):
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={"content": message})
    except:
        pass


# Supabase setup
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ER:LC API
ERLC_BASE_URL = "https://api.policeroleplay.community/v1"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True


class PaginationView(discord.ui.View):
    def __init__(self, embeds: list[discord.Embed]):
        super().__init__(timeout=60)
        self.embeds = embeds
        self.current_page = 0

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.gray, disabled=True)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.gray)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    def update_buttons(self):
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.embeds) - 1


def erlc_headers():
    return {
        "Server-Key": os.environ.get("ERLC_KEY", ""),
        "Content-Type": "application/json"
    }


def add_log(guild_id: str, action: str, target_user: str, role_name: str, performed_by: str, reason: str, notes: str = "") -> int:
    try:
        result = supabase.table("audit_logs").insert({
            "guild_id": guild_id,
            "action": action,
            "target_user": target_user,
            "role_name": role_name,
            "performed_by": performed_by,
            "reason": reason,
            "notes": notes,
            "is_voided": False
        }).execute()
        return result.data[0]["id"] if result.data else 0
    except Exception as e:
        print(f"Failed to add log: {e}")
        return 0


def get_guild_config(guild_id: str) -> dict:
    try:
        result = supabase.table("guild_configs").select("*").eq("guild_id", guild_id).execute()
        return result.data[0] if result.data else {}
    except Exception as e:
        print(f"Failed to get guild config: {e}")
        return {}


def save_guild_config(guild_id: str, config: dict):
    try:
        existing = supabase.table("guild_configs").select("guild_id").eq("guild_id", guild_id).execute()
        if existing.data:
            supabase.table("guild_configs").update(config).eq("guild_id", guild_id).execute()
        else:
            supabase.table("guild_configs").insert({"guild_id": guild_id, **config}).execute()
    except Exception as e:
        print(f"Failed to save guild config: {e}")


def has_role(user, role_ids_str: str) -> bool:
    if not role_ids_str:
        return False
    role_ids = [r.strip() for r in role_ids_str.split(",") if r.strip()]
    return any(str(r.id) in role_ids for r in user.roles)


async def send_to_channel(guild: discord.Guild, channel_id: str, embed: discord.Embed):
    if not channel_id:
        return
    try:
        channel = guild.get_channel(int(channel_id))
        if channel and isinstance(channel, discord.TextChannel):
            await channel.send(embed=embed)
    except Exception as e:
        print(f"Failed to send to channel {channel_id}: {e}")


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        print("Slash commands synced.")

    async def on_ready(self):
        if self.user:
            print(f'Logged in as {self.user.name} (ID: {self.user.id})')
        print('------')


bot = MyBot()

# ──────────────────────────────────────────
# WEBHOOK COMMAND LOGGING (ADDED)
# ──────────────────────────────────────────

@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    try:
        name = interaction.command.name if interaction.command else "unknown"
        log_webhook(f"📌 CMD /{name} | {interaction.user} | {interaction.guild.name if interaction.guild else 'DM'}")
    except:
        pass


# ──────────────────────────────────────────
# ERLC COMMANDS (ONLY WEBHOOK ADDED INSIDE)
# ──────────────────────────────────────────

@bot.tree.command(name="erlc_status", description="Shows live ER:LC server status and player count")
async def erlc_status(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server", headers=erlc_headers(), timeout=10)

        log_webhook(f"ERLC STATUS CHECK by {interaction.user}")

        if response.status_code == 200:
            data = response.json()
            embed = discord.Embed(
                title="🚔 ER:LC Server Status",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Server Name", value=data.get("Name", "N/A"), inline=True)
            embed.add_field(name="Players Online", value=str(data.get("CurrentPlayers", 0)), inline=True)
            embed.add_field(name="Max Players", value=str(data.get("MaxPlayers", 0)), inline=True)
            embed.add_field(name="Join Key", value=data.get("JoinKey", "N/A"), inline=True)
            embed.add_field(name="Queue", value=str(data.get("Queue", 0)), inline=True)
            await interaction.followup.send(embed=embed)

        elif response.status_code == 422:
            log_webhook("ERLC STATUS: no session")
            await interaction.followup.send("No active session found. Start a session first!", ephemeral=True)
        else:
            log_webhook(f"ERLC STATUS FAIL {response.status_code}")
            await interaction.followup.send(f"Failed to fetch server status. Error: {response.status_code}", ephemeral=True)

    except Exception as e:
        log_webhook(f"ERLC STATUS ERROR {e}")
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


@bot.tree.command(name="players", description="Shows who is currently in the ER:LC server")
async def players(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server/players", headers=erlc_headers(), timeout=10)

        log_webhook(f"PLAYER LIST requested by {interaction.user}")

        if response.status_code == 200:
            data = response.json()

            embed = discord.Embed(
                title=f"🎮 Players Online",
                color=discord.Color.blue(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.description = "\n".join([f"{p.get('Player')} — {p.get('Team')}" for p in data[:20]])

            await interaction.followup.send(embed=embed)

        else:
            log_webhook(f"PLAYER LIST FAIL {response.status_code}")
            await interaction.followup.send("Failed to fetch players.", ephemeral=True)

    except Exception as e:
        log_webhook(f"PLAYER LIST ERROR {e}")
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


@bot.tree.command(name="killlogs", description="Shows recent kill logs from the ER:LC server")
async def killlogs(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server/killlogs", headers=erlc_headers(), timeout=10)

        log_webhook(f"KILLLOGS requested by {interaction.user}")

        if response.status_code == 200:
            data = response.json()
            embed = discord.Embed(title="💀 Kill Logs", color=discord.Color.red())

            for log in data[:10]:
                embed.add_field(
                    name=f"{log.get('Killer')} → {log.get('Killed')}",
                    value=log.get("Kill"),
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        else:
            await interaction.followup.send("Failed to fetch kill logs.", ephemeral=True)

    except Exception as e:
        log_webhook(f"KILLLOG ERROR {e}")
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


@bot.tree.command(name="modcalls", description="Shows active mod calls from the ER:LC server")
async def modcalls(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server/modcalls", headers=erlc_headers(), timeout=10)

        log_webhook(f"MODCALLS requested by {interaction.user}")

        if response.status_code == 200:
            data = response.json()
            embed = discord.Embed(title="📢 Mod Calls", color=discord.Color.orange())

            for call in data[:10]:
                embed.add_field(
                    name=call.get("Caller"),
                    value=call.get("Reason"),
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        else:
            await interaction.followup.send("Failed to fetch mod calls.", ephemeral=True)

    except Exception as e:
        log_webhook(f"MODCALL ERROR {e}")
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


# ──────────────────────────────────────────
# SESSION COMMANDS (WEBHOOK ADDED ONLY)
# ──────────────────────────────────────────

@bot.tree.command(name="session_start", description="Announces a session is starting")
async def session_start(interaction: discord.Interaction):
    await interaction.response.defer()

    log_webhook(f"SESSION START by {interaction.user}")

    # unchanged logic continues...
    config = get_guild_config(str(interaction.guild.id))
    session_channel_id = config.get("session_channel_id")

    embed = discord.Embed(
        title="🚔 Session Starting!",
        description="A new session is starting!",
        color=discord.Color.green(),
        timestamp=datetime.now(timezone.utc)
    )

    if session_channel_id:
        await send_to_channel(interaction.guild, session_channel_id, embed)

    await interaction.followup.send("Session started!", ephemeral=True)


@bot.tree.command(name="session_end", description="Announces a session has ended")
async def session_end(interaction: discord.Interaction):
    await interaction.response.defer()

    log_webhook(f"SESSION END by {interaction.user}")

    config = get_guild_config(str(interaction.guild.id))
    session_channel_id = config.get("session_channel_id")

    embed = discord.Embed(
        title="🔴 Session Ended",
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc)
    )

    if session_channel_id:
        await send_to_channel(interaction.guild, session_channel_id, embed)

    await interaction.followup.send("Session ended!", ephemeral=True)


# ──────────────────────────────────────────
# ERROR HANDLER (WEBHOOK ADDED)
# ──────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    log_webhook(f"ERROR: {error}")

    if isinstance(error, app_commands.MissingPermissions):
        msg = "You don't have permission to use this command."
    else:
        msg = f"An error occurred: {error}"

    if not interaction.response.is_done():
        await interaction.response.send_message(msg, ephemeral=True)
    else:
        await interaction.followup.send(msg, ephemeral=True)


bot.run(os.environ["DISCORD_TOKEN"])
