import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import requests
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

# Supabase setup
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ER:LC API
ERLC_BASE_URL = "https://api.policeroleplay.community/v1"

# Webhook
LOG_WEBHOOK = os.environ.get("LOG_WEBHOOK", "")

# Track players already seen in ER:LC server
seen_erlc_players = set()

intents = discord.Intents.default()
intents.members = True
intents.message_content = True


def send_webhook(title: str, description: str, color: int, fields: list = None):
    if not LOG_WEBHOOK:
        return
    try:
        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fields": fields or []
        }
        requests.post(LOG_WEBHOOK, json={"embeds": [embed]}, timeout=5)
    except Exception as e:
        print(f"Webhook error: {e}")


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


def send_erlc_pm(username: str, message: str):
    """Send an in-game PM to a player via ER:LC API."""
    try:
        requests.post(
            f"{ERLC_BASE_URL}/server/command",
            headers=erlc_headers(),
            json={"command": f":pm {username} {message}"},
            timeout=10
        )
    except Exception as e:
        print(f"Failed to send ER:LC PM: {e}")


def get_roblox_user(username: str) -> dict:
    """Fetch Roblox user info by username."""
    try:
        r = requests.post(
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": [username], "excludeBannedUsers": False},
            timeout=10
        )
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                user = data[0]
                # Get extra profile info
                uid = user["id"]
                profile = requests.get(f"https://users.roblox.com/v1/users/{uid}", timeout=10).json()
                avatar = requests.get(f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={uid}&size=420x420&format=Png", timeout=10).json()
                avatar_url = avatar.get("data", [{}])[0].get("imageUrl", "")
                return {
                    "id": uid,
                    "name": profile.get("name", username),
                    "displayName": profile.get("displayName", username),
                    "description": profile.get("description", ""),
                    "created": profile.get("created", ""),
                    "avatar_url": avatar_url
                }
    except Exception as e:
        print(f"Roblox API error: {e}")
    return {}


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)

    async def setup_hook(self):
        await self.tree.sync()
        self.erlc_join_tracker.start()
        print("Slash commands synced.")

    async def on_ready(self):
        if self.user:
            print(f'Logged in as {self.user.name} (ID: {self.user.id})')
            send_webhook("✅ Bot Online", f"**{self.user.name}** has connected to Discord.", 0x4ade80)
        print('------')

    async def on_member_join(self, member: discord.Member):
        guild_id = str(member.guild.id)
        config = get_guild_config(guild_id)
        try:
            supabase.table("discord_join_logs").insert({
                "guild_id": guild_id,
                "discord_id": str(member.id),
                "username": member.name,
                "action": "join"
            }).execute()
        except Exception as e:
            print(f"Failed to log Discord join: {e}")

        send_webhook("📥 Member Joined", f"**{member.name}** joined the server", 0x4ade80, [
            {"name": "Server", "value": member.guild.name, "inline": True},
            {"name": "Account Created", "value": member.created_at.strftime("%b %d, %Y"), "inline": True}
        ])

        welcome_channel_id = config.get("welcome_channel_id")
        if welcome_channel_id:
            try:
                channel = member.guild.get_channel(int(welcome_channel_id))
                if channel:
                    embed = discord.Embed(
                        title="👋 Welcome!",
                        description=f"Welcome to **{member.guild.name}**, {member.mention}!",
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)
                    await channel.send(embed=embed)
            except Exception as e:
                print(f"Failed to send welcome message: {e}")

    async def on_member_remove(self, member: discord.Member):
        guild_id = str(member.guild.id)
        try:
            supabase.table("discord_join_logs").insert({
                "guild_id": guild_id,
                "discord_id": str(member.id),
                "username": member.name,
                "action": "leave"
            }).execute()
        except Exception as e:
            print(f"Failed to log Discord leave: {e}")

        send_webhook("📤 Member Left", f"**{member.name}** left the server", 0xf87171, [
            {"name": "Server", "value": member.guild.name, "inline": True}
        ])

    @tasks.loop(seconds=15)
    async def erlc_join_tracker(self):
        """Poll ER:LC every 15 seconds and detect new player joins."""
        global seen_erlc_players
        try:
            r = requests.get(f"{ERLC_BASE_URL}/server/players", headers=erlc_headers(), timeout=10)
            if r.status_code != 200:
                return

            current_players = r.json()
            current_names = {p.get("Player", "") for p in current_players}

            # Find new players
            new_players = [p for p in current_players if p.get("Player") not in seen_erlc_players]

            for player in new_players:
                name = player.get("Player", "Unknown")
                team = player.get("Team", "Unknown")

                # Log to Supabase
                try:
                    supabase.table("erlc_join_logs").insert({
                        "guild_id": "global",
                        "player_name": name,
                        "team": team
                    }).execute()
                except Exception as e:
                    print(f"Failed to log ER:LC join: {e}")

                # Send in-game PM
                send_erlc_pm(name, "Welcome! Your join has been logged by the Maryland State Roleplay Bot.")

                # Send webhook
                send_webhook("🎮 ER:LC Player Joined", f"**{name}** joined the ER:LC server", 0x4ade80, [
                    {"name": "Team", "value": team, "inline": True},
                    {"name": "Time", "value": datetime.now(timezone.utc).strftime("%H:%M:%S UTC"), "inline": True}
                ])

            # Find players who left
            left_players = seen_erlc_players - current_names
            for name in left_players:
                send_webhook("🚪 ER:LC Player Left", f"**{name}** left the ER:LC server", 0xf87171)

            seen_erlc_players = current_names

        except Exception as e:
            print(f"ER:LC tracker error: {e}")

    @erlc_join_tracker.before_loop
    async def before_tracker(self):
        await self.wait_until_ready()


bot = MyBot()


# ──────────────────────────────────────────
# ROBLOX COMMANDS
# ──────────────────────────────────────────

@bot.tree.command(name="link", description="Link your Roblox account to your Discord")
@app_commands.describe(username="Your Roblox username")
async def link(interaction: discord.Interaction, username: str):
    await interaction.response.defer(ephemeral=True)

    roblox = get_roblox_user(username)
    if not roblox:
        await interaction.followup.send("Roblox user not found. Check your username and try again.", ephemeral=True)
        return

    try:
        existing = supabase.table("roblox_links").select("*").eq("discord_id", str(interaction.user.id)).execute()
        if existing.data:
            supabase.table("roblox_links").update({
                "roblox_username": roblox["name"],
                "roblox_id": roblox["id"],
                "linked_at": datetime.now(timezone.utc).isoformat()
            }).eq("discord_id", str(interaction.user.id)).execute()
            msg = f"Updated your linked Roblox account to **{roblox['name']}**!"
        else:
            supabase.table("roblox_links").insert({
                "discord_id": str(interaction.user.id),
                "roblox_username": roblox["name"],
                "roblox_id": roblox["id"]
            }).execute()
            msg = f"Successfully linked your Discord to Roblox account **{roblox['name']}**!"

        embed = discord.Embed(
            title="✅ Roblox Account Linked",
            description=msg,
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Roblox Username", value=roblox["name"], inline=True)
        embed.add_field(name="Roblox ID", value=str(roblox["id"]), inline=True)
        if roblox.get("avatar_url"):
            embed.set_thumbnail(url=roblox["avatar_url"])

        await interaction.followup.send(embed=embed, ephemeral=True)

        send_webhook("🔗 Roblox Account Linked", f"**{interaction.user.display_name}** linked to **{roblox['name']}**", 0x4ade80, [
            {"name": "Discord", "value": interaction.user.display_name, "inline": True},
            {"name": "Roblox", "value": roblox["name"], "inline": True}
        ])
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


@bot.tree.command(name="robloxinfo", description="Shows Roblox profile info for a user")
@app_commands.describe(username="Roblox username to look up (leave blank to look up your linked account)")
async def robloxinfo(interaction: discord.Interaction, username: str = ""):
    await interaction.response.defer()

    lookup_username = username
    if not lookup_username:
        try:
            result = supabase.table("roblox_links").select("*").eq("discord_id", str(interaction.user.id)).execute()
            if result.data:
                lookup_username = result.data[0]["roblox_username"]
            else:
                await interaction.followup.send("You haven't linked a Roblox account yet! Use `/link` first.", ephemeral=True)
                return
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)
            return

    roblox = get_roblox_user(lookup_username)
    if not roblox:
        await interaction.followup.send("Roblox user not found.", ephemeral=True)
        return

    try:
        friends_r = requests.get(f"https://friends.roblox.com/v1/users/{roblox['id']}/friends/count", timeout=10)
        friend_count = friends_r.json().get("count", 0) if friends_r.status_code == 200 else "N/A"
    except:
        friend_count = "N/A"

    embed = discord.Embed(
        title=f"Roblox Profile — {roblox['name']}",
        color=discord.Color.blue(),
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Display Name", value=roblox.get("displayName", "N/A"), inline=True)
    embed.add_field(name="User ID", value=str(roblox["id"]), inline=True)
    embed.add_field(name="Friends", value=str(friend_count), inline=True)
    if roblox.get("created"):
        try:
            created = datetime.fromisoformat(roblox["created"].replace("Z", "+00:00")).strftime("%b %d, %Y")
            embed.add_field(name="Account Created", value=created, inline=True)
        except:
            pass
    if roblox.get("description"):
        embed.add_field(name="Bio", value=roblox["description"][:200] or "No bio", inline=False)
    embed.add_field(name="Profile Link", value=f"[View Profile](https://www.roblox.com/users/{roblox['id']}/profile)", inline=False)
    if roblox.get("avatar_url"):
        embed.set_thumbnail(url=roblox["avatar_url"])

    await interaction.followup.send(embed=embed)

    send_webhook("🔍 Roblox Info Checked", f"Roblox info checked by **{interaction.user.display_name}**", 0x60a5fa, [
        {"name": "Looked Up", "value": roblox["name"], "inline": True}
    ])


@bot.tree.command(name="inserver", description="Check if a linked player is in your ER:LC server")
@app_commands.describe(member="Discord member to check (leave blank to check yourself)")
async def inserver(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer()

    target = member or interaction.user

    try:
        result = supabase.table("roblox_links").select("*").eq("discord_id", str(target.id)).execute()
        if not result.data:
            await interaction.followup.send(f"**{target.display_name}** hasn't linked a Roblox account yet.", ephemeral=True)
            return
        roblox_username = result.data[0]["roblox_username"]
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)
        return

    try:
        r = requests.get(f"{ERLC_BASE_URL}/server/players", headers=erlc_headers(), timeout=10)
        if r.status_code != 200:
            await interaction.followup.send("Could not fetch ER:LC player list.", ephemeral=True)
            return

        players = r.json()
        found = next((p for p in players if p.get("Player", "").lower() == roblox_username.lower()), None)

        if found:
            embed = discord.Embed(
                title="✅ Player Found in Server",
                description=f"**{target.display_name}** is currently in the ER:LC server!",
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Roblox Username", value=roblox_username, inline=True)
            embed.add_field(name="Team", value=found.get("Team", "Unknown"), inline=True)
        else:
            embed = discord.Embed(
                title="❌ Player Not in Server",
                description=f"**{target.display_name}** is not currently in the ER:LC server.",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name="Roblox Username", value=roblox_username, inline=True)

        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


# ──────────────────────────────────────────
# ER:LC COMMANDS
# ──────────────────────────────────────────

@bot.tree.command(name="erlc_status", description="Shows live ER:LC server status and player count")
async def erlc_status(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server", headers=erlc_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            embed = discord.Embed(title="🚔 ER:LC Server Status", color=discord.Color.green(), timestamp=datetime.now(timezone.utc))
            embed.add_field(name="Server Name", value=data.get("Name", "N/A"), inline=True)
            embed.add_field(name="Players Online", value=str(data.get("CurrentPlayers", 0)), inline=True)
            embed.add_field(name="Max Players", value=str(data.get("MaxPlayers", 0)), inline=True)
            embed.add_field(name="Join Key", value=data.get("JoinKey", "N/A"), inline=True)
            embed.add_field(name="Queue", value=str(data.get("Queue", 0)), inline=True)
            await interaction.followup.send(embed=embed)
            send_webhook("🚔 ER:LC Status Checked", f"Status checked by **{interaction.user.display_name}**", 0x60a5fa, [
                {"name": "Players", "value": str(data.get("CurrentPlayers", 0)), "inline": True},
                {"name": "Join Key", "value": data.get("JoinKey", "N/A"), "inline": True}
            ])
        elif response.status_code == 422:
            await interaction.followup.send("No active session found.", ephemeral=True)
        else:
            await interaction.followup.send(f"Error: {response.status_code}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


@bot.tree.command(name="players", description="Shows who is currently in the ER:LC server")
async def players(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server/players", headers=erlc_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            if not data:
                await interaction.followup.send("No players currently in the server.", ephemeral=True)
                return
            pages = []
            chunks = [data[i:i+20] for i in range(0, len(data), 20)]
            for chunk in chunks:
                embed = discord.Embed(title=f"🎮 Players Online ({len(data)} total)", color=discord.Color.blue(), timestamp=datetime.now(timezone.utc))
                embed.description = "\n".join(f"**{p.get('Player','?')}** — {p.get('Team','?')}" for p in chunk)
                embed.set_footer(text=f"Page {len(pages)+1} of {len(chunks)}")
                pages.append(embed)
            if len(pages) == 1:
                await interaction.followup.send(embed=pages[0])
            else:
                view = PaginationView(pages)
                view.update_buttons()
                await interaction.followup.send(embed=pages[0], view=view)
            send_webhook("🎮 Players List Checked", f"Player list checked by **{interaction.user.display_name}**", 0x60a5fa, [
                {"name": "Total Players", "value": str(len(data)), "inline": True}
            ])
        elif response.status_code == 422:
            await interaction.followup.send("No active session found.", ephemeral=True)
        else:
            await interaction.followup.send(f"Error: {response.status_code}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


@bot.tree.command(name="killlogs", description="Shows recent kill logs from the ER:LC server")
async def killlogs(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server/killlogs", headers=erlc_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            if not data:
                await interaction.followup.send("No kill logs found.", ephemeral=True)
                return
            embed = discord.Embed(title="💀 Recent Kill Logs", color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
            embed.description = "\n".join(f"**{l.get('Killer','?')}** killed **{l.get('Killed','?')}** with `{l.get('Kill','?')}`" for l in data[:20])
            config = get_guild_config(str(interaction.guild.id)) if interaction.guild else {}
            if config.get("killlog_channel_id") and interaction.guild:
                await send_to_channel(interaction.guild, config["killlog_channel_id"], embed)
            await interaction.followup.send(embed=embed)
            send_webhook("💀 Kill Logs Checked", f"Kill logs checked by **{interaction.user.display_name}**", 0xf87171, [
                {"name": "Total Kills", "value": str(len(data)), "inline": True}
            ])
        elif response.status_code == 422:
            await interaction.followup.send("No active session found.", ephemeral=True)
        else:
            await interaction.followup.send(f"Error: {response.status_code}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


@bot.tree.command(name="modcalls", description="Shows active mod calls from the ER:LC server")
async def modcalls(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server/modcalls", headers=erlc_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            if not data:
                await interaction.followup.send("No active mod calls.", ephemeral=True)
                return
            embed = discord.Embed(title="📢 Active Mod Calls", color=discord.Color.orange(), timestamp=datetime.now(timezone.utc))
            embed.description = "\n".join(f"**{c.get('Caller','?')}** — {c.get('Reason','?')}" for c in data[:20])
            config = get_guild_config(str(interaction.guild.id)) if interaction.guild else {}
            if config.get("modcall_channel_id") and interaction.guild:
                await send_to_channel(interaction.guild, config["modcall_channel_id"], embed)
            await interaction.followup.send(embed=embed)
            send_webhook("📢 Mod Calls Checked", f"Mod calls checked by **{interaction.user.display_name}**", 0xfb923c, [
                {"name": "Active Mod Calls", "value": str(len(data)), "inline": True}
            ])
        elif response.status_code == 422:
            await interaction.followup.send("No active session found.", ephemeral=True)
        else:
            await interaction.followup.send(f"Error: {response.status_code}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


@bot.tree.command(name="session_start", description="Announces a session is starting")
async def session_start(interaction: discord.Interaction):
    await interaction.response.defer()
    if not interaction.guild:
        await interaction.followup.send("This command must be used in a server.", ephemeral=True)
        return
    config = get_guild_config(str(interaction.guild.id))
    custom_message = config.get("session_ping_message", "A new session is starting! Join now!")
    try:
        server_data = {}
        r = requests.get(f"{ERLC_BASE_URL}/server", headers=erlc_headers(), timeout=10)
        if r.status_code == 200:
            server_data = r.json()
    except:
        pass
    embed = discord.Embed(title="🚔 Session Starting!", description=custom_message, color=discord.Color.green(), timestamp=datetime.now(timezone.utc))
    if server_data:
        embed.add_field(name="Players Online", value=str(server_data.get("CurrentPlayers", 0)), inline=True)
        embed.add_field(name="Join Key", value=server_data.get("JoinKey", "N/A"), inline=True)
    embed.set_footer(text=f"Started by {interaction.user.display_name}")
    if config.get("session_channel_id"):
        await send_to_channel(interaction.guild, config["session_channel_id"], embed)
        await interaction.followup.send("Session ping sent!", ephemeral=True)
    else:
        await interaction.followup.send(embed=embed)
    add_log(str(interaction.guild.id), "session_start", "Server", "N/A", interaction.user.display_name, "Session started")
    send_webhook("🟢 Session Started", f"Session started by **{interaction.user.display_name}**", 0x4ade80, [
        {"name": "Server", "value": interaction.guild.name, "inline": True},
        {"name": "Join Key", "value": server_data.get("JoinKey", "N/A"), "inline": True}
    ])


@bot.tree.command(name="session_end", description="Announces a session has ended")
async def session_end(interaction: discord.Interaction):
    await interaction.response.defer()
    if not interaction.guild:
        await interaction.followup.send("This command must be used in a server.", ephemeral=True)
        return
    config = get_guild_config(str(interaction.guild.id))
    embed = discord.Embed(title="🔴 Session Ended", description="The session has ended. Thanks for playing!", color=discord.Color.red(), timestamp=datetime.now(timezone.utc))
    embed.set_footer(text=f"Ended by {interaction.user.display_name}")
    if config.get("session_channel_id"):
        await send_to_channel(interaction.guild, config["session_channel_id"], embed)
        await interaction.followup.send("Session end ping sent!", ephemeral=True)
    else:
        await interaction.followup.send(embed=embed)
    add_log(str(interaction.guild.id), "session_end", "Server", "N/A", interaction.user.display_name, "Session ended")
    send_webhook("🔴 Session Ended", f"Session ended by **{interaction.user.display_name}**", 0xf87171)


# ──────────────────────────────────────────
# SETUP
# ──────────────────────────────────────────

@bot.tree.command(name="setup", description="Configure roles and log channel for this server")
@app_commands.describe(
    staff_role="The role for bot staff",
    admin_role="The role for bot admins",
    hr_role="The HR role (required for promote/infraction commands)",
    log_channel="The channel where bot actions will be logged"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction, staff_role: discord.Role, admin_role: discord.Role, hr_role: discord.Role, log_channel: discord.TextChannel):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        await interaction.followup.send("This command must be used in a server.", ephemeral=True)
        return
    save_guild_config(str(interaction.guild.id), {
        "staff_role_id": str(staff_role.id),
        "admin_role_id": str(admin_role.id),
        "hr_role_id": str(hr_role.id),
        "log_channel_id": str(log_channel.id)
    })
    add_log(str(interaction.guild.id), "setup", "Server Config", "N/A", interaction.user.display_name, "Initial Setup")
    send_webhook("⚙️ Bot Setup", f"Bot configured by **{interaction.user.display_name}**", 0xc084fc)
    await interaction.followup.send(f"Configured! Staff: {staff_role.mention} | Admin: {admin_role.mention} | HR: {hr_role.mention} | Log: {log_channel.mention}", ephemeral=True)


# ──────────────────────────────────────────
# PROMOTE
# ──────────────────────────────────────────

@bot.tree.command(name="promote", description="Promotes a member by adding a role")
@app_commands.describe(member="The member to promote", role="The role to add", reason="The reason for promotion", notes="Additional notes (Optional)")
@app_commands.choices(notes=[
    app_commands.Choice(name="Exceptional Performance", value="Exceptional Performance"),
    app_commands.Choice(name="Longevity/Loyalty", value="Longevity/Loyalty"),
    app_commands.Choice(name="Leadership Skills", value="Leadership Skills"),
    app_commands.Choice(name="Community Contribution", value="Community Contribution")
])
async def promote(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str, notes: str = ""):
    try:
        await interaction.response.defer(ephemeral=False)
    except:
        return
    if not interaction.guild:
        await interaction.followup.send("Must be used in a server.", ephemeral=True)
        return
    config = get_guild_config(str(interaction.guild.id))
    has_admin_perm = interaction.user.guild_permissions.administrator if hasattr(interaction.user, "guild_permissions") else False
    is_hr = any(str(r.id) == config.get("hr_role_id") for r in interaction.user.roles) if hasattr(interaction.user, "roles") and config.get("hr_role_id") else False
    has_promote_role = has_role(interaction.user, config.get("promote_role_ids", "")) if hasattr(interaction.user, "roles") else False
    if not (is_hr or has_admin_perm or has_promote_role):
        await interaction.followup.send("You do not have permission to promote members.", ephemeral=True)
        return
    try:
        await member.add_roles(role)
        log_id = add_log(str(interaction.guild.id), "promote", member.display_name, role.name, interaction.user.display_name, reason, notes)
        embed = discord.Embed(title="Member Promoted", description=f"Promoted {member.mention} to **{role.name}**\n\n**By:** {interaction.user.mention}", color=discord.Color.green(), timestamp=interaction.created_at)
        embed.add_field(name="Target", value=member.display_name, inline=True)
        embed.add_field(name="New Role", value=role.name, inline=True)
        embed.add_field(name="By", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Log ID", value=str(log_id), inline=True)
        if notes:
            embed.add_field(name="Notes", value=notes, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.followup.send(content=f"{member.mention} {interaction.user.mention}", embed=embed)
        promote_channel = config.get("promote_channel_id") or config.get("log_channel_id")
        if promote_channel:
            await send_to_channel(interaction.guild, promote_channel, embed)
        send_webhook("🟢 Member Promoted", f"**{member.display_name}** was promoted", 0x4ade80, [
            {"name": "By", "value": interaction.user.display_name, "inline": True},
            {"name": "Role", "value": role.name, "inline": True},
            {"name": "Reason", "value": reason, "inline": False},
            {"name": "Log ID", "value": str(log_id), "inline": True}
        ])
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to add that role.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


# ──────────────────────────────────────────
# INFRACTION
# ──────────────────────────────────────────

@bot.tree.command(name="infraction_issue", description="Issues an infraction to a member by removing a role")
@app_commands.describe(member="The member to issue an infraction to", role="The role to remove", reason="The reason for the infraction", notes="Additional notes (Optional)")
@app_commands.choices(notes=[
    app_commands.Choice(name="Inactivity", value="Inactivity"),
    app_commands.Choice(name="Rule Violation", value="Rule Violation"),
    app_commands.Choice(name="Request", value="Request"),
    app_commands.Choice(name="Other", value="Other")
])
async def infraction_issue(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str, notes: str = ""):
    try:
        await interaction.response.defer(ephemeral=False)
    except:
        return
    if not interaction.guild:
        await interaction.followup.send("Must be used in a server.", ephemeral=True)
        return
    config = get_guild_config(str(interaction.guild.id))
    has_admin_perm = interaction.user.guild_permissions.administrator if hasattr(interaction.user, "guild_permissions") else False
    is_hr = any(str(r.id) == config.get("hr_role_id") for r in interaction.user.roles) if hasattr(interaction.user, "roles") and config.get("hr_role_id") else False
    has_infraction_role = has_role(interaction.user, config.get("infraction_role_ids", "")) if hasattr(interaction.user, "roles") else False
    if not (is_hr or has_admin_perm or has_infraction_role):
        await interaction.followup.send("You do not have permission to issue infractions.", ephemeral=True)
        return
    try:
        await member.remove_roles(role)
        log_id = add_log(str(interaction.guild.id), "infraction", member.display_name, role.name, interaction.user.display_name, reason, notes)
        embed = discord.Embed(title="Infraction Issued", description=f"Infraction issued to {member.mention} removing **{role.name}**\n\n**By:** {interaction.user.mention}", color=discord.Color.red(), timestamp=interaction.created_at)
        embed.add_field(name="Target", value=member.display_name, inline=True)
        embed.add_field(name="Removed Role", value=role.name, inline=True)
        embed.add_field(name="By", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="ID", value=str(log_id), inline=True)
        if notes:
            embed.add_field(name="Notes", value=notes, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)
        await interaction.followup.send(content=f"{member.mention} {interaction.user.mention}", embed=embed)
        infraction_channel = config.get("infraction_channel_id") or config.get("log_channel_id")
        if infraction_channel:
            await send_to_channel(interaction.guild, infraction_channel, embed)
        send_webhook("🔴 Infraction Issued", f"**{member.display_name}** received an infraction", 0xf87171, [
            {"name": "By", "value": interaction.user.display_name, "inline": True},
            {"name": "Role", "value": role.name, "inline": True},
            {"name": "Reason", "value": reason, "inline": False},
            {"name": "ID", "value": str(log_id), "inline": True}
        ])
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to remove that role.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


# ──────────────────────────────────────────
# VOID INFRACTION
# ──────────────────────────────────────────

@bot.tree.command(name="void_infraction", description="Voids an infraction using its ID")
@app_commands.describe(infraction_id="The ID of the infraction to void")
async def void_infraction(interaction: discord.Interaction, infraction_id: int):
    await interaction.response.defer(ephemeral=True)
    if not interaction.guild:
        await interaction.followup.send("Must be used in a server.", ephemeral=True)
        return
    config = get_guild_config(str(interaction.guild.id))
    has_admin_perm = interaction.user.guild_permissions.administrator if hasattr(interaction.user, "guild_permissions") else False
    is_hr = any(str(r.id) == config.get("hr_role_id") for r in interaction.user.roles) if hasattr(interaction.user, "roles") and config.get("hr_role_id") else False
    is_admin = any(str(r.id) == config.get("admin_role_id") for r in interaction.user.roles) if hasattr(interaction.user, "roles") and config.get("admin_role_id") else False
    has_void_role = has_role(interaction.user, config.get("void_role_ids", "")) if hasattr(interaction.user, "roles") else False
    if not (is_hr or is_admin or has_admin_perm or has_void_role):
        await interaction.followup.send("You do not have permission to void infractions.", ephemeral=True)
        return
    try:
        result = supabase.table("audit_logs").update({"is_voided": True}).eq("id", infraction_id).execute()
        if not result.data:
            await interaction.followup.send(f"Infraction #{infraction_id} not found.", ephemeral=True)
            return
        add_log(str(interaction.guild.id), "void", f"Infraction #{infraction_id}", "N/A", interaction.user.display_name, "Infraction Voided")
        embed = discord.Embed(title="Infraction Voided", description=f"Infraction **#{infraction_id}** voided by {interaction.user.mention}.", color=discord.Color.orange(), timestamp=interaction.created_at)
        await interaction.followup.send(embed=embed, ephemeral=True)
        void_channel = config.get("void_channel_id") or config.get("log_channel_id")
        if void_channel:
            await send_to_channel(interaction.guild, void_channel, embed)
        send_webhook("🟠 Infraction Voided", f"Infraction **#{infraction_id}** voided by **{interaction.user.display_name}**", 0xfb923c)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


# ──────────────────────────────────────────
# HISTORY
# ──────────────────────────────────────────

@bot.tree.command(name="history", description="Shows audit logs from the past 24 hours")
async def history(interaction: discord.Interaction):
    await interaction.response.defer()
    now = datetime.now(timezone.utc)
    one_day_ago = (now - timedelta(days=1)).isoformat()
    guild_id = str(interaction.guild.id) if interaction.guild else None
    try:
        result = supabase.table("audit_logs").select("*").eq("guild_id", guild_id).gte("timestamp", one_day_ago).order("timestamp", desc=True).execute()
        recent_logs = result.data or []
    except Exception as e:
        await interaction.followup.send(f"Failed to fetch logs: {e}", ephemeral=True)
        return
    if not recent_logs:
        await interaction.followup.send("No audit logs found for the past 24 hours.", ephemeral=True)
        return
    pages = []
    for i in range(0, len(recent_logs), 20):
        chunk = recent_logs[i:i + 20]
        embed = discord.Embed(title="Audit Log History (Past 24h)", color=discord.Color.blue(), timestamp=now)
        log_entries = []
        for log in chunk:
            action = log.get('action', 'Action').capitalize()
            target = log.get('target_user', 'N/A')
            role = log.get('role_name', 'N/A')
            by = log.get('performed_by', 'Unknown')
            voided = log.get('is_voided', False)
            try:
                time_str = datetime.fromisoformat(log['timestamp']).strftime("%H:%M:%S")
            except:
                time_str = "00:00:00"
            voided_str = " ~~VOIDED~~" if voided else ""
            if action.lower() in ["promote", "demote"]:
                log_entries.append(f"`{time_str}` **{action}** {target} ({role}) by {by}{voided_str}")
            else:
                log_entries.append(f"`{time_str}` **{action}** on {target} by {by}{voided_str}")
        embed.description = "\n".join(log_entries)
        embed.set_footer(text=f"Page {len(pages) + 1} of {(len(recent_logs) - 1) // 20 + 1}")
        pages.append(embed)
    if len(pages) == 1:
        await interaction.followup.send(embed=pages[0])
    else:
        view = PaginationView(pages)
        view.update_buttons()
        await interaction.followup.send(embed=pages[0], view=view)
    send_webhook("📋 History Checked", f"Audit history checked by **{interaction.user.display_name}**", 0x60a5fa)


# ──────────────────────────────────────────
# USERINFO
# ──────────────────────────────────────────

@bot.tree.command(name="userinfo", description="Displays information about a user")
@app_commands.describe(member="The member to get information about")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer()
    target_member = member or (interaction.user if isinstance(interaction.user, discord.Member) else None)
    if not target_member:
        await interaction.followup.send("Could not find member information.", ephemeral=True)
        return
    guild_id = str(interaction.guild.id) if interaction.guild else None
    try:
        result = supabase.table("audit_logs").select("*").eq("guild_id", guild_id).eq("performed_by", target_member.display_name).execute()
        user_logs = result.data or []
    except:
        user_logs = []

    # Check if they have a linked Roblox account
    roblox_info = "Not linked"
    try:
        roblox_result = supabase.table("roblox_links").select("*").eq("discord_id", str(target_member.id)).execute()
        if roblox_result.data:
            roblox_info = roblox_result.data[0]["roblox_username"]
    except:
        pass

    embed = discord.Embed(title=f"User Information - {target_member.display_name}", color=discord.Color.blue(), timestamp=interaction.created_at)
    embed.set_thumbnail(url=target_member.display_avatar.url)
    embed.add_field(name="Username", value=target_member.name, inline=True)
    embed.add_field(name="ID", value=str(target_member.id), inline=True)
    embed.add_field(name="Roblox Account", value=roblox_info, inline=True)
    embed.add_field(name="Account Created", value=target_member.created_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name="Joined Server", value=target_member.joined_at.strftime("%b %d, %Y") if target_member.joined_at else "Unknown", inline=True)
    embed.add_field(name="Bot Commands Ran", value=str(len(user_logs)), inline=True)
    if user_logs:
        last_actions = []
        for log in user_logs[:5]:
            action = log.get('action', 'Unknown').capitalize()
            target = log.get('target_user', 'N/A')
            try:
                time_str = datetime.fromisoformat(log['timestamp']).strftime("%H:%M")
            except:
                time_str = "00:00"
            last_actions.append(f"`{time_str}` **{action}** on {target}")
        embed.add_field(name="Recent Actions", value="\n".join(last_actions), inline=False)
    roles = [role.mention for role in target_member.roles[1:]]
    embed.add_field(name=f"Roles [{len(roles)}]", value=" ".join(roles) if roles else "None", inline=False)
    await interaction.followup.send(embed=embed)
    send_webhook("👤 User Info Checked", f"User info for **{target_member.display_name}** checked", 0x60a5fa)


# ──────────────────────────────────────────
# HELP
# ──────────────────────────────────────────

@bot.tree.command(name="help", description="Get help with the bot commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="Maryland State Roleplay Bot - Command Help", description="Here are the available commands:", color=discord.Color.purple())
    embed.add_field(name="/promote", value="Promote a member (HR role required)", inline=False)
    embed.add_field(name="/infraction_issue", value="Issue an infraction to a member (HR role required)", inline=False)
    embed.add_field(name="/void_infraction", value="Void an infraction by ID (HR/Admin required)", inline=False)
    embed.add_field(name="/history", value="View audit logs from the past 24 hours", inline=False)
    embed.add_field(name="/userinfo", value="View information about a user", inline=False)
    embed.add_field(name="/setup", value="Configure roles and log channel (Admin only)", inline=False)
    embed.add_field(name="/embed", value="Send a custom embed to a channel (Admin only)", inline=False)
    embed.add_field(name="─── Roblox ───", value="\u200b", inline=False)
    embed.add_field(name="/link", value="Link your Roblox account to your Discord", inline=False)
    embed.add_field(name="/robloxinfo", value="View Roblox profile info", inline=False)
    embed.add_field(name="/inserver", value="Check if a linked player is in the ER:LC server", inline=False)
    embed.add_field(name="─── ER:LC ───", value="\u200b", inline=False)
    embed.add_field(name="/erlc_status", value="View live server status and player count", inline=False)
    embed.add_field(name="/players", value="View who is currently in the ER:LC server", inline=False)
    embed.add_field(name="/killlogs", value="View recent kill logs", inline=False)
    embed.add_field(name="/modcalls", value="View active mod calls", inline=False)
    embed.add_field(name="/session_start", value="Announce a session is starting", inline=False)
    embed.add_field(name="/session_end", value="Announce a session has ended", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ──────────────────────────────────────────
# EMBED
# ──────────────────────────────────────────

@bot.tree.command(name="embed", description="Send a custom embed message to a channel")
@app_commands.describe(channel="The channel to send the embed to", title="The title of the embed", description="The description/body of the embed", color="The color (red, green, blue, gold, purple, orange)", image_url="An image or thumbnail URL (Optional)")
@app_commands.checks.has_permissions(administrator=True)
async def embed_command(interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str, color: str = "blue", image_url: str = ""):
    await interaction.response.defer(ephemeral=True)
    color_map = {"red": discord.Color.red(), "green": discord.Color.green(), "blue": discord.Color.blue(), "gold": discord.Color.gold(), "purple": discord.Color.purple(), "orange": discord.Color.orange()}
    embed = discord.Embed(title=title, description=description, color=color_map.get(color.lower(), discord.Color.blue()), timestamp=datetime.now(timezone.utc))
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"Posted by {interaction.user.display_name}")
    try:
        await channel.send(embed=embed)
        await interaction.followup.send(f"Embed sent to {channel.mention}!", ephemeral=True)
        send_webhook("📨 Embed Sent", f"Embed sent by **{interaction.user.display_name}**", 0xc084fc, [
            {"name": "Channel", "value": f"#{channel.name}", "inline": True},
            {"name": "Title", "value": title, "inline": True}
        ])
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to send messages in that channel.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)


# ──────────────────────────────────────────
# ERROR HANDLER
# ──────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You don't have permission to use this command."
    else:
        msg = f"An error occurred: {error}"
        send_webhook("⚠️ Command Error", str(error), 0xf87171)
    if not interaction.response.is_done():
        await interaction.response.send_message(msg, ephemeral=True)
    else:
        await interaction.followup.send(msg, ephemeral=True)


bot.run(os.environ["DISCORD_TOKEN"])
