import discord
from discord import app_commands
from discord.ext import commands
import os
import requests
from datetime import datetime, timedelta, timezone

# In-memory storage
audit_logs = []
guild_configs = {}
log_id_counter = 1

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
    global log_id_counter
    log = {
        "id": log_id_counter,
        "guildId": guild_id,
        "action": action,
        "targetUser": target_user,
        "roleName": role_name,
        "performedBy": performed_by,
        "reason": reason,
        "notes": notes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "isVoided": False
    }
    audit_logs.append(log)
    log_id_counter += 1
    return log["id"]


def get_guild_config(guild_id: str) -> dict:
    return guild_configs.get(guild_id, {})


async def log_to_channel(guild: discord.Guild, config: dict, embed: discord.Embed):
    log_channel_id = config.get("logChannelId")
    if not log_channel_id:
        return
    try:
        channel = guild.get_channel(int(log_channel_id))
        if channel and isinstance(channel, discord.TextChannel):
            await channel.send(embed=embed)
    except Exception as e:
        print(f"Failed to send log to channel: {e}")


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
# ER:LC COMMANDS
# ──────────────────────────────────────────

@bot.tree.command(name="erlc_status", description="Shows live ER:LC server status and player count")
async def erlc_status(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        response = requests.get(f"{ERLC_BASE_URL}/server", headers=erlc_headers(), timeout=10)
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
            await interaction.followup.send("No active session found. Start a session first!", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed to fetch server status. Error: {response.status_code}", ephemeral=True)
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
                embed = discord.Embed(
                    title=f"🎮 Players Online ({len(data)} total)",
                    color=discord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )
                player_list = []
                for player in chunk:
                    name = player.get("Player", "Unknown")
                    team = player.get("Team", "Unknown")
                    player_list.append(f"**{name}** — {team}")
                embed.description = "\n".join(player_list)
                embed.set_footer(text=f"Page {len(pages)+1} of {len(chunks)}")
                pages.append(embed)

            if len(pages) == 1:
                await interaction.followup.send(embed=pages[0])
            else:
                view = PaginationView(pages)
                view.update_buttons()
                await interaction.followup.send(embed=pages[0], view=view)
        elif response.status_code == 422:
            await interaction.followup.send("No active session found.", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed to fetch players. Error: {response.status_code}", ephemeral=True)
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

            embed = discord.Embed(
                title="💀 Recent Kill Logs",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            entries = []
            for log in data[:20]:
                killer = log.get("Killer", "Unknown")
                killed = log.get("Killed", "Unknown")
                weapon = log.get("Kill", "Unknown")
                entries.append(f"**{killer}** killed **{killed}** with `{weapon}`")
            embed.description = "\n".join(entries)
            await interaction.followup.send(embed=embed)
        elif response.status_code == 422:
            await interaction.followup.send("No active session found.", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed to fetch kill logs. Error: {response.status_code}", ephemeral=True)
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

            embed = discord.Embed(
                title="📢 Active Mod Calls",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc)
            )
            entries = []
            for call in data[:20]:
                caller = call.get("Caller", "Unknown")
                reason = call.get("Reason", "No reason provided")
                entries.append(f"**{caller}** — {reason}")
            embed.description = "\n".join(entries)
            await interaction.followup.send(embed=embed)
        elif response.status_code == 422:
            await interaction.followup.send("No active session found.", ephemeral=True)
        else:
            await interaction.followup.send(f"Failed to fetch mod calls. Error: {response.status_code}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


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
async def setup(
    interaction: discord.Interaction,
    staff_role: discord.Role,
    admin_role: discord.Role,
    hr_role: discord.Role,
    log_channel: discord.TextChannel
):
    await interaction.response.defer(ephemeral=True)

    if not interaction.guild:
        await interaction.followup.send("This command must be used in a server.", ephemeral=True)
        return

    guild_configs[str(interaction.guild.id)] = {
        "staffRoleId": str(staff_role.id),
        "adminRoleId": str(admin_role.id),
        "hrRoleId": str(hr_role.id),
        "logChannelId": str(log_channel.id)
    }

    add_log(
        str(interaction.guild.id), "setup", "Server Config", "N/A",
        interaction.user.display_name, "Initial Setup / Role Update",
        f"Staff: {staff_role.name}, Admin: {admin_role.name}, HR: {hr_role.name}, Log: #{log_channel.name}"
    )

    await interaction.followup.send(
        f"Successfully configured server:\n"
        f"**Staff:** {staff_role.mention}\n"
        f"**Admin:** {admin_role.mention}\n"
        f"**HR:** {hr_role.mention}\n"
        f"**Log Channel:** {log_channel.mention}",
        ephemeral=True
    )


# ──────────────────────────────────────────
# PROMOTE
# ──────────────────────────────────────────

@bot.tree.command(name="promote", description="Promotes a member by adding a role")
@app_commands.describe(
    member="The member to promote",
    role="The role to add",
    reason="The reason for promotion",
    notes="Additional notes (Optional)"
)
@app_commands.choices(notes=[
    app_commands.Choice(name="Exceptional Performance", value="Exceptional Performance"),
    app_commands.Choice(name="Longevity/Loyalty", value="Longevity/Loyalty"),
    app_commands.Choice(name="Leadership Skills", value="Leadership Skills"),
    app_commands.Choice(name="Community Contribution", value="Community Contribution")
])
async def promote(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str, notes: str = ""):
    try:
        await interaction.response.defer(ephemeral=False)
    except Exception as e:
        print(f"Failed to defer: {e}")
        return

    if not interaction.guild:
        await interaction.followup.send("This command must be used in a server.", ephemeral=True)
        return

    config = get_guild_config(str(interaction.guild.id))
    hr_role_id = config.get("hrRoleId")
    has_admin_perm = interaction.user.guild_permissions.administrator if hasattr(interaction.user, "guild_permissions") else False
    is_hr = any(str(r.id) == hr_role_id for r in interaction.user.roles) if hasattr(interaction.user, "roles") and hr_role_id else False

    if not (is_hr or has_admin_perm):
        await interaction.followup.send("You do not have permission to promote members. The HR role is required.", ephemeral=True)
        return

    try:
        await member.add_roles(role)
        log_id = add_log(str(interaction.guild.id), "promote", member.display_name, role.name,
                         interaction.user.display_name, reason, notes)

        embed = discord.Embed(
            title="Member Promoted",
            description=f"Successfully promoted {member.mention} to **{role.name}**\n\n**Performed By:** {interaction.user.mention}",
            color=discord.Color.green(),
            timestamp=interaction.created_at
        )
        embed.add_field(name="Target User", value=member.display_name, inline=True)
        embed.add_field(name="New Role", value=role.name, inline=True)
        embed.add_field(name="Action Taken By", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Log ID", value=str(log_id), inline=True)
        if notes:
            embed.add_field(name="Notes", value=notes, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)

        await interaction.followup.send(content=f"{member.mention} {interaction.user.mention}", embed=embed)
        await log_to_channel(interaction.guild, config, embed)
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to add that role.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


# ──────────────────────────────────────────
# INFRACTION
# ──────────────────────────────────────────

@bot.tree.command(name="infraction_issue", description="Issues an infraction to a member by removing a role")
@app_commands.describe(
    member="The member to issue an infraction to",
    role="The role to remove",
    reason="The reason for the infraction",
    notes="Additional notes (Optional)"
)
@app_commands.choices(notes=[
    app_commands.Choice(name="Inactivity", value="Inactivity"),
    app_commands.Choice(name="Rule Violation", value="Rule Violation"),
    app_commands.Choice(name="Request", value="Request"),
    app_commands.Choice(name="Other", value="Other")
])
async def infraction_issue(interaction: discord.Interaction, member: discord.Member, role: discord.Role, reason: str, notes: str = ""):
    try:
        await interaction.response.defer(ephemeral=False)
    except Exception as e:
        print(f"Failed to defer: {e}")
        return

    if not interaction.guild:
        await interaction.followup.send("This command must be used in a server.", ephemeral=True)
        return

    config = get_guild_config(str(interaction.guild.id))
    hr_role_id = config.get("hrRoleId")
    has_admin_perm = interaction.user.guild_permissions.administrator if hasattr(interaction.user, "guild_permissions") else False
    is_hr = any(str(r.id) == hr_role_id for r in interaction.user.roles) if hasattr(interaction.user, "roles") and hr_role_id else False

    if not (is_hr or has_admin_perm):
        await interaction.followup.send("You do not have permission to issue infractions. The HR role is required.", ephemeral=True)
        return

    try:
        await member.remove_roles(role)
        log_id = add_log(str(interaction.guild.id), "infraction", member.display_name, role.name,
                         interaction.user.display_name, reason, notes)

        embed = discord.Embed(
            title="Infraction Issued",
            description=f"Successfully issued infraction to {member.mention} by removing **{role.name}**\n\n**Performed By:** {interaction.user.mention}",
            color=discord.Color.red(),
            timestamp=interaction.created_at
        )
        embed.add_field(name="Target User", value=member.display_name, inline=True)
        embed.add_field(name="Removed Role", value=role.name, inline=True)
        embed.add_field(name="Action Taken By", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Infraction ID", value=str(log_id), inline=True)
        if notes:
            embed.add_field(name="Notes", value=notes, inline=False)
        embed.set_thumbnail(url=member.display_avatar.url)

        await interaction.followup.send(content=f"{member.mention} {interaction.user.mention}", embed=embed)
        await log_to_channel(interaction.guild, config, embed)
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to remove that role.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


# ──────────────────────────────────────────
# VOID INFRACTION
# ──────────────────────────────────────────

@bot.tree.command(name="void_infraction", description="Voids an infraction using its ID")
@app_commands.describe(infraction_id="The ID of the infraction to void")
async def void_infraction(interaction: discord.Interaction, infraction_id: int):
    await interaction.response.defer(ephemeral=True)

    if not interaction.guild:
        await interaction.followup.send("This command must be used in a server.", ephemeral=True)
        return

    config = get_guild_config(str(interaction.guild.id))
    hr_role_id = config.get("hrRoleId")
    admin_role_id = config.get("adminRoleId")
    has_admin_perm = interaction.user.guild_permissions.administrator if hasattr(interaction.user, "guild_permissions") else False
    is_hr = any(str(r.id) == hr_role_id for r in interaction.user.roles) if hasattr(interaction.user, "roles") and hr_role_id else False
    is_admin = any(str(r.id) == admin_role_id for r in interaction.user.roles) if hasattr(interaction.user, "roles") and admin_role_id else False

    if not (is_hr or is_admin or has_admin_perm):
        await interaction.followup.send("You do not have permission to void infractions. HR or Admin role required.", ephemeral=True)
        return

    target_log = next((log for log in audit_logs if log["id"] == infraction_id), None)
    if not target_log:
        await interaction.followup.send(f"Infraction #{infraction_id} not found.", ephemeral=True)
        return

    target_log["isVoided"] = True
    add_log(str(interaction.guild.id), "void", f"Infraction #{infraction_id}", "N/A",
            interaction.user.display_name, "Infraction Voided", f"Voided infraction #{infraction_id}")

    embed = discord.Embed(
        title="Infraction Voided",
        description=f"Infraction **#{infraction_id}** has been voided by {interaction.user.mention}.",
        color=discord.Color.orange(),
        timestamp=interaction.created_at
    )
    await interaction.followup.send(embed=embed, ephemeral=True)
    await log_to_channel(interaction.guild, config, embed)


# ──────────────────────────────────────────
# HISTORY
# ──────────────────────────────────────────

@bot.tree.command(name="history", description="Shows audit logs from the past 24 hours")
async def history(interaction: discord.Interaction):
    await interaction.response.defer()

    now = datetime.now(timezone.utc)
    one_day_ago = now - timedelta(days=1)

    guild_id = str(interaction.guild.id) if interaction.guild else None
    recent_logs = []
    for log in audit_logs:
        try:
            if guild_id and log.get("guildId") != guild_id:
                continue
            log_time = datetime.fromisoformat(log['timestamp'])
            if log_time >= one_day_ago:
                recent_logs.append(log)
        except (ValueError, KeyError):
            continue

    if not recent_logs:
        await interaction.followup.send("No audit logs found for the past 24 hours.", ephemeral=True)
        return

    pages = []
    for i in range(0, len(recent_logs), 20):
        chunk = recent_logs[i:i + 20]
        embed = discord.Embed(
            title="Audit Log History (Past 24h)",
            color=discord.Color.blue(),
            timestamp=now
        )
        log_entries = []
        for log in chunk:
            action = log.get('action', 'Action').capitalize()
            target = log.get('targetUser', 'N/A')
            role = log.get('roleName', 'N/A')
            by = log.get('performedBy', 'Unknown')
            voided = log.get('isVoided', False)
            try:
                time_str = datetime.fromisoformat(log['timestamp']).strftime("%H:%M:%S")
            except (ValueError, KeyError):
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


# ──────────────────────────────────────────
# USERINFO
# ──────────────────────────────────────────

@bot.tree.command(name="userinfo", description="Displays information about a user")
@app_commands.describe(member="The member to get information about")
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    await interaction.response.defer()

    target_member: discord.Member
    if member is not None:
        target_member = member
    elif isinstance(interaction.user, discord.Member):
        target_member = interaction.user
    else:
        await interaction.followup.send("Could not find member information.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id) if interaction.guild else None
    user_logs = [log for log in audit_logs if log.get('performedBy') == target_member.display_name and (not guild_id or log.get('guildId') == guild_id)]
    commands_ran = len(user_logs)
    shared_servers = sum(1 for guild in bot.guilds if guild.get_member(target_member.id))

    embed = discord.Embed(
        title=f"User Information - {target_member.display_name}",
        color=discord.Color.blue(),
        timestamp=interaction.created_at
    )
    embed.set_thumbnail(url=target_member.display_avatar.url)
    embed.add_field(name="Username", value=target_member.name, inline=True)
    embed.add_field(name="ID", value=str(target_member.id), inline=True)
    embed.add_field(name="Account Created", value=target_member.created_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name="Joined Server", value=target_member.joined_at.strftime("%b %d, %Y") if target_member.joined_at else "Unknown", inline=True)
    embed.add_field(name="Bot Commands Ran", value=str(commands_ran), inline=True)
    embed.add_field(name="Servers with Bot", value=str(shared_servers), inline=True)

    if user_logs:
        last_actions = []
        for log in user_logs[:5]:
            action = log.get('action', 'Unknown').capitalize()
            target = log.get('targetUser', 'N/A')
            try:
                time_str = datetime.fromisoformat(log['timestamp']).strftime("%H:%M")
            except (ValueError, KeyError):
                time_str = "00:00"
            last_actions.append(f"`{time_str}` **{action}** on {target}")
        embed.add_field(name="Recent Actions", value="\n".join(last_actions), inline=False)

    roles = [role.mention for role in target_member.roles[1:]]
    embed.add_field(name=f"Roles [{len(roles)}]", value=" ".join(roles) if roles else "None", inline=False)

    await interaction.followup.send(embed=embed)


# ──────────────────────────────────────────
# HELP
# ──────────────────────────────────────────

@bot.tree.command(name="help", description="Get help with the bot commands")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Maryland State Roleplay Bot - Command Help",
        description="Here are the available commands:",
        color=discord.Color.purple()
    )
    embed.add_field(name="/promote", value="Promote a member (HR role required)", inline=False)
    embed.add_field(name="/infraction_issue", value="Issue an infraction to a member (HR role required)", inline=False)
    embed.add_field(name="/void_infraction", value="Void an infraction by ID (HR/Admin required)", inline=False)
    embed.add_field(name="/history", value="View audit logs from the past 24 hours", inline=False)
    embed.add_field(name="/userinfo", value="View information about a user", inline=False)
    embed.add_field(name="/setup", value="Configure roles and log channel (Admin only)", inline=False)
    embed.add_field(name="/embed", value="Send a custom embed to a channel (Admin only)", inline=False)
    embed.add_field(name="─── ER:LC ───", value="\u200b", inline=False)
    embed.add_field(name="/erlc_status", value="View live server status and player count", inline=False)
    embed.add_field(name="/players", value="View who is currently in the ER:LC server", inline=False)
    embed.add_field(name="/killlogs", value="View recent kill logs", inline=False)
    embed.add_field(name="/modcalls", value="View active mod calls", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ──────────────────────────────────────────
# EMBED
# ──────────────────────────────────────────

@bot.tree.command(name="embed", description="Send a custom embed message to a channel")
@app_commands.describe(
    channel="The channel to send the embed to",
    title="The title of the embed",
    description="The description/body of the embed",
    color="The color of the embed (red, green, blue, gold, purple, orange)",
    image_url="An image or thumbnail URL (Optional)"
)
@app_commands.checks.has_permissions(administrator=True)
async def embed_command(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    description: str,
    color: str = "blue",
    image_url: str = ""
):
    await interaction.response.defer(ephemeral=True)

    color_map = {
        "red": discord.Color.red(),
        "green": discord.Color.green(),
        "blue": discord.Color.blue(),
        "gold": discord.Color.gold(),
        "purple": discord.Color.purple(),
        "orange": discord.Color.orange()
    }
    embed_color = color_map.get(color.lower(), discord.Color.blue())

    embed = discord.Embed(
        title=title,
        description=description,
        color=embed_color,
        timestamp=datetime.now(timezone.utc)
    )

    if image_url:
        embed.set_image(url=image_url)

    embed.set_footer(text=f"Posted by {interaction.user.display_name}")

    try:
        await channel.send(embed=embed)
        await interaction.followup.send(f"Embed sent to {channel.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("I don't have permission to send messages in that channel.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)


# ──────────────────────────────────────────
# ERROR HANDLER
# ──────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "You don't have permission to use this command."
    else:
        msg = f"An error occurred: {error}"
    if not interaction.response.is_done():
        await interaction.response.send_message(msg, ephemeral=True)
    else:
        await interaction.followup.send(msg, ephemeral=True)


bot.run(os.environ["DISCORD_TOKEN"])
