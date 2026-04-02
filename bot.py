import discord
from discord import app_commands
from discord.ext import commands
import os
import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# In-memory storage
audit_logs = []
guild_configs = {}
log_id_counter = 1

# AI conversation history: {user_id: [{"role": ..., "content": ...}]}
ai_conversations = {}

SAMBANOVA_API_URL = "https://api.sambanova.ai/v1/chat/completions"
SAMBANOVA_MODEL = "DeepSeek-R1"

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

    add_log(str(interaction.guild.id), "setup", "Server Config", "N/A", interaction.user.display_name,
            "Initial Setup / Role Update",
            f"Staff: {staff_role.name}, Admin: {admin_role.name}, HR: {hr_role.name}, Log: #{log_channel.name}")

    await interaction.followup.send(
        f"Successfully configured server:\n"
        f"**Staff:** {staff_role.mention}\n"
        f"**Admin:** {admin_role.mention}\n"
        f"**HR:** {hr_role.mention}\n"
        f"**Log Channel:** {log_channel.mention}",
        ephemeral=True
    )


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
        embed.add_field(name="Action Taken By", value=interaction.user.
