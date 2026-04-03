import discord
from discord import app_commands
from discord.ext import commands
import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# In-memory storage
audit_logs = []
guild_configs = {}
log_id_counter = 1

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

    add_log(str(interaction.guild.id), "setup",
