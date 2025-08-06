import discord
from discord.ext import commands, tasks
import json
import os
import random
import time
import asyncio
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import sqlite3
import threading
from typing import Dict, List, Optional, Any
import matplotlib.pyplot as plt
import io
import base64
import logging
import shutil
import traceback

# ==========================================
# 🔧 CONFIGURATION & SETUP
# ==========================================

TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 901837385380294686
DATA_FILE = "balances.json"
DB_FILE = "casino_data.db"
BACKUP_DIR = "backups"
LOG_FILE = "casino.log"

# ==========================================
# 📝 LOGGING SETUP
# ==========================================

def setup_logging():
    """Setup comprehensive logging system"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        handlers=[
            logging.FileHandler(f'logs/{LOG_FILE}', encoding='utf-8'),
            logging.StreamHandler()  # Console output
        ]
    )
    
    # Create casino-specific logger
    casino_logger = logging.getLogger('casino')
    casino_logger.setLevel(logging.INFO)
    
    # Discord.py logging
    discord_logger = logging.getLogger('discord')
    discord_logger.setLevel(logging.WARNING)  # Reduce discord spam
    
    return casino_logger

# Initialize logger
logger = setup_logging()

# 🎨 AESTHETIC CONFIGURATION
CASINO_THEME = {
    "primary": 0xFFD700,    # Gold
    "success": 0x00FF00,    # Green
    "danger": 0xFF0000,     # Red
    "warning": 0xFFAA00,    # Orange
    "info": 0x0099FF,       # Blue
    "premium": 0x8A2BE2     # Purple
}

CASINO_ICON = "https://cdn.discordapp.com/emojis/1234567890123456789.png"
FOOTER_TEXT = "Casino Paradise 🎰 | Play smart. Win big."

# 🎰 ODDS CONFIGURATION (House Always Wins)
ODDS_CONFIG = {
    "withdraw_threshold": 200_000_000_000_000,  # 200T
    "balance_thresholds": {
        180_000_000_000_000: 0.10,  # 180T+ → 10% win rate
        150_000_000_000_000: 0.15,  # 150T+ → 15% win rate
        100_000_000_000_000: 0.25,  # 100T+ → 25% win rate
        0: 0.35                     # Normal → 35% win rate max
    },
    "game_multipliers": {
        "coinflip": {"base_odds": 0.30, "payout": 1.8},
        "slot": {"base_odds": 0.25, "jackpot_odds": 0.02, "partial_odds": 0.15, "jackpot_payout": 4.5, "partial_payout": 1.8},
        "roulette": {"red_black_odds": 0.25, "green_odds": 0.01, "red_black_payout": 1.9, "green_payout": 12},
        "blackjack": {"base_odds": 0.35, "blackjack_bonus": 2.2},
        "dice": {"jackpot_odds": 0.05, "good_odds": 0.20, "jackpot_payout": 5.5, "good_payout": 1.8}
    }
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(
    command_prefix="!", 
    intents=intents, 
    help_command=None,
    case_insensitive=True,
    strip_after_prefix=True
)

# Global variables for advanced features
user_sessions = {}
rate_limits = defaultdict(lambda: defaultdict(list))
tournaments = {}
guilds_data = {}
shop_items = {}
user_limits = {}
casino_global_stats = {"total_bets": 0, "total_wagered": 0, "total_won": 0, "total_lost": 0}

# PvP System
active_challenges = {}  # {challenger_id: {opponent_id, game_type, bet_amount, message_id}}
active_pvp_games = {}   # {game_id: {players, game_data, spectators}}

# ==========================================
# 🔄 AUTOMATIC BACKUP SYSTEM
# ==========================================

@tasks.loop(minutes=30)
async def auto_backup():
    """Automatically backup data every 30 minutes"""
    try:
        create_backup()
        logger.info("⏰ Automatic backup completed")
    except Exception as e:
        logger.error(f"❌ Auto backup failed: {e}")

@tasks.loop(minutes=5)
async def auto_save():
    """Automatically save data every 5 minutes"""
    try:
        save_data()
        logger.info("💾 Auto-save completed")
    except Exception as e:
        logger.error(f"❌ Auto-save failed: {e}")

# ==========================================
# 💾 DATABASE MANAGEMENT SYSTEM
# ==========================================

def init_database():
    """Initialize SQLite database for better data management"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id TEXT PRIMARY KEY,
                total_profit INTEGER DEFAULT 0,
                biggest_win INTEGER DEFAULT 0,
                biggest_loss INTEGER DEFAULT 0,
                game_stats TEXT DEFAULT '{}',
                session_data TEXT DEFAULT '{}',
                daily_wagered INTEGER DEFAULT 0,
                weekly_wagered INTEGER DEFAULT 0,
                monthly_wagered INTEGER DEFAULT 0,
                last_reset_daily TEXT DEFAULT '',
                last_reset_weekly TEXT DEFAULT '',
                last_reset_monthly TEXT DEFAULT ''
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS global_stats (
                stat_name TEXT PRIMARY KEY,
                stat_value INTEGER DEFAULT 0,
                last_updated TEXT DEFAULT ''
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_limits (
                user_id TEXT PRIMARY KEY,
                daily_limit INTEGER DEFAULT 0,
                weekly_limit INTEGER DEFAULT 0,
                self_excluded_until TEXT DEFAULT '',
                warnings INTEGER DEFAULT 0
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                tournament_id TEXT PRIMARY KEY,
                name TEXT,
                game_type TEXT,
                prize_pool INTEGER,
                participants TEXT DEFAULT '{}',
                start_time TEXT,
                end_time TEXT,
                status TEXT DEFAULT 'active'
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guilds (
                guild_id TEXT PRIMARY KEY,
                name TEXT,
                members TEXT DEFAULT '{}',
                total_wins INTEGER DEFAULT 0,
                total_wagered INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1
            )
        ''')

        # Add audit log table for tracking all changes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT,
                action TEXT,
                details TEXT,
                balance_before INTEGER,
                balance_after INTEGER
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        logger.error(traceback.format_exc())
        logger.warning("⚠️ Continuing without database features")

def load_data():
    """Load user data from JSON file with recovery mechanisms"""
    try:
        if not os.path.exists(DATA_FILE):
            logger.info("📂 Data file doesn't exist, creating new one...")
            with open(DATA_FILE, "w") as f:
                json.dump({}, f)
            return {}
        
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            logger.info(f"✅ Loaded data successfully - {len(data)} users")
            return data
            
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON decode error: {e}")
        logger.info("🔄 Attempting to restore from backup...")
        
        if restore_from_backup():
            logger.info("✅ Successfully restored from backup")
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        else:
            logger.critical("❌ Failed to restore from backup, starting fresh")
            return {}
            
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}")
        logger.error(traceback.format_exc())
        
        # Try backup restoration
        if restore_from_backup():
            logger.info("✅ Successfully restored from backup")
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        else:
            logger.warning("🔧 Creating new data file...")
            return {}

def save_data(data=None):
    """Save user data to JSON file with backup"""
    try:
        data_to_save = balances if data is None else data
        
        # Create backup before saving
        create_backup()
        
        # Save data
        with open(DATA_FILE, "w") as f:
            json.dump(data_to_save, f, indent=4)
        
        logger.info(f"💾 Data saved successfully - {len(data_to_save)} users")
        
    except Exception as e:
        logger.error(f"❌ Error saving data: {e}")
        logger.error(traceback.format_exc())
        
        # Try to restore from backup if save fails
        try:
            restore_from_backup()
            logger.info("🔄 Restored data from backup after save failure")
        except Exception as restore_error:
            logger.critical(f"❌ CRITICAL: Failed to save AND restore data: {restore_error}")

def create_backup():
    """Create timestamped backup of current data"""
    try:
        # Ensure backup directory exists
        os.makedirs(BACKUP_DIR, exist_ok=True)
        
        # Create timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Backup JSON data
        if os.path.exists(DATA_FILE):
            backup_file = os.path.join(BACKUP_DIR, f"balances_{timestamp}.json")
            shutil.copy2(DATA_FILE, backup_file)
            logger.info(f"📦 Created backup: {backup_file}")
        
        # Backup database
        if os.path.exists(DB_FILE):
            db_backup_file = os.path.join(BACKUP_DIR, f"casino_data_{timestamp}.db")
            shutil.copy2(DB_FILE, db_backup_file)
            logger.info(f"📦 Created database backup: {db_backup_file}")
        
        # Clean old backups (keep last 10)
        cleanup_old_backups()
        
    except Exception as e:
        logger.error(f"❌ Error creating backup: {e}")

def cleanup_old_backups():
    """Remove old backup files, keep last 10"""
    try:
        if not os.path.exists(BACKUP_DIR):
            return
            
        # Get all backup files
        backup_files = []
        for file in os.listdir(BACKUP_DIR):
            if file.startswith(('balances_', 'casino_data_')):
                file_path = os.path.join(BACKUP_DIR, file)
                backup_files.append((file_path, os.path.getctime(file_path)))
        
        # Sort by creation time (newest first)
        backup_files.sort(key=lambda x: x[1], reverse=True)
        
        # Remove old backups (keep 10 most recent)
        for file_path, _ in backup_files[10:]:
            os.remove(file_path)
            logger.info(f"🗑️ Removed old backup: {os.path.basename(file_path)}")
            
    except Exception as e:
        logger.error(f"❌ Error cleaning up backups: {e}")

def restore_from_backup():
    """Restore data from most recent backup"""
    try:
        if not os.path.exists(BACKUP_DIR):
            raise Exception("No backup directory found")
        
        # Find most recent backup
        backup_files = []
        for file in os.listdir(BACKUP_DIR):
            if file.startswith('balances_') and file.endswith('.json'):
                file_path = os.path.join(BACKUP_DIR, file)
                backup_files.append((file_path, os.path.getctime(file_path)))
        
        if not backup_files:
            raise Exception("No backup files found")
        
        # Get most recent backup
        most_recent = max(backup_files, key=lambda x: x[1])[0]
        
        # Restore data
        with open(most_recent, 'r') as f:
            restored_data = json.load(f)
        
        global balances
        balances = restored_data
        
        # Save restored data
        with open(DATA_FILE, "w") as f:
            json.dump(balances, f, indent=4)
        
        logger.info(f"🔄 Successfully restored from backup: {os.path.basename(most_recent)}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error restoring from backup: {e}")
        return False

def log_user_action(user_id, action, details):
    """Log user actions for audit trail"""
    try:
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "user_id": str(user_id),
            "action": action,
            "details": details
        }
        logger.info(f"👤 USER ACTION: {user_id} - {action} - {details}")
    except Exception as e:
        logger.error(f"❌ Error logging user action: {e}")

def get_user(uid):
    """Get or create user data with default values"""
    uid = str(uid)
    is_new_user = uid not in balances
    
    if is_new_user:
        balances[uid] = {
            "trial": 25_000_000_000_000,
            "premium": 0,
            "mode": "trial",
            "last_daily": 0,
            "last_weekly": 0,
            "bets": 0,
            "wins": 0,
            "losses": 0,
            "achievements": {},
            "cosmetics": {"theme": "default", "badges": []},
            "boosters": {},
            "guild_id": None
        }
        init_user_stats(uid)
        log_user_action(uid, "USER_CREATED", "New user account created")
        logger.info(f"👤 New user created: {uid}")
    else:
        # Add missing fields for existing users
        user = balances[uid]
        if "achievements" not in user:
            user["achievements"] = {}
        if "cosmetics" not in user:
            user["cosmetics"] = {"theme": "default", "badges": []}
        if "boosters" not in user:
            user["boosters"] = {}
        if "guild_id" not in user:
            user["guild_id"] = None
        # Ensure cosmetics has the required structure
        if "badges" not in user["cosmetics"]:
            user["cosmetics"]["badges"] = []
        if "theme" not in user["cosmetics"]:
            user["cosmetics"]["theme"] = "default"
    
    return balances[uid]

def init_user_stats(user_id):
    """Initialize user statistics in database"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO user_stats (user_id) VALUES (?)', (user_id,))
        cursor.execute('INSERT OR IGNORE INTO user_limits (user_id) VALUES (?)', (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database error in init_user_stats: {e}")
        # Continue without database if it fails

# Initialize database and load data
init_database()
balances = load_data()

# ==========================================
# 🎨 AESTHETIC UTILITY FUNCTIONS
# ==========================================

def create_casino_embed(title, description="", color=None, user=None, is_pvp=False):
    """Create a beautifully styled casino embed"""
    if color is None:
        color = CASINO_THEME["primary"]

    # Check if user has diamond theme and this is a PvP message
    if user and is_pvp:
        user_data = get_user(user.id)
        if user_data["cosmetics"]["theme"] == "diamond_theme":
            color = 0x1E90FF  # Special diamond blue color
    
    embed = discord.Embed(title=f"🎰 {title}", description=description, color=color)
    embed.set_author(name="Casino Paradise", icon_url=CASINO_ICON)
    embed.set_footer(text=FOOTER_TEXT, icon_url=CASINO_ICON)
    embed.timestamp = datetime.now()

    if user:
        embed.set_thumbnail(url=user.display_avatar.url)

    return embed

def get_user_win_rate(user_id):
    """Calculate dynamic win rate based on user's balance"""
    user = get_user(user_id)
    current_balance = user[user["mode"]]

    for threshold, win_rate in sorted(ODDS_CONFIG["balance_thresholds"].items(), reverse=True):
        if current_balance >= threshold:
            return win_rate

    return ODDS_CONFIG["balance_thresholds"][0]

def check_rate_limit(user_id, command, limit_per_minute=5):
    """Enhanced rate limiting with cooldowns"""
    now = time.time()
    user_commands = rate_limits[user_id][command]

    # Remove old entries
    rate_limits[user_id][command] = [t for t in user_commands if now - t < 60]

    if len(rate_limits[user_id][command]) >= limit_per_minute:
        return False

    rate_limits[user_id][command].append(now)
    return True

async def animate_loading(message, frames, duration=0.5):
    """Create loading animation for suspense"""
    for frame in frames:
        embed = create_casino_embed("🎲 Rolling...", frame, CASINO_THEME["info"])
        await message.edit(embed=embed)
        await asyncio.sleep(duration)

# ==========================================
# 🔧 UTILITY FUNCTIONS
# ==========================================

def format_sheckles(amount):
    """Format large numbers with suffixes (T, B, M)"""
    if amount >= 1_000_000_000_000:
        return f"{amount / 1_000_000_000_000:.2f}T"
    elif amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.2f}B"
    elif amount >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M"
    return f"{amount:,}"

def format_user_name_for_pvp(user, user_id=None):
    """Format username with diamond theme enhancement for PvP"""
    if user_id is None:
        user_id = user.id
    
    user_data = get_user(user_id)
    if user_data["cosmetics"]["theme"] == "diamond_theme":
        return f"💎 {user.display_name} 💎"
    return user.display_name

def parse_sheckles(text):
    """Parse user input like '10T', '5B', '1M' to actual numbers"""
    text = text.lower().replace(",", "")
    if text == "all":
        return "all"
    if text.endswith("t"):
        return int(float(text[:-1]) * 1_000_000_000_000)
    elif text.endswith("b"):
        return int(float(text[:-1]) * 1_000_000_000)
    elif text.endswith("m"):
        return int(float(text[:-1]) * 1_000_000)
    return int(float(text))

def update_user_stats(user_id, game_type, bet_amount, win_amount, won=False):
    """Update detailed user statistics with audit logging"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        profit_loss = win_amount - bet_amount if won else -bet_amount
        user = get_user(user_id)
        balance_before = user[user["mode"]]

        cursor.execute('''
            UPDATE user_stats 
            SET total_profit = total_profit + ?,
                biggest_win = MAX(biggest_win, ?),
                biggest_loss = MAX(biggest_loss, ?)
            WHERE user_id = ?
        ''', (profit_loss, win_amount if won else 0, bet_amount if not won else 0, user_id))

        # Log to audit table
        cursor.execute('''
            INSERT INTO audit_log (user_id, action, details, balance_before, balance_after)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            user_id, 
            f"GAME_{game_type.upper()}_{'WIN' if won else 'LOSS'}",
            f"Bet: {bet_amount}, Win: {win_amount}, Profit: {profit_loss}",
            balance_before,
            user[user["mode"]]
        ))

        casino_global_stats["total_bets"] += 1
        casino_global_stats["total_wagered"] += bet_amount
        if won:
            casino_global_stats["total_won"] += win_amount
        else:
            casino_global_stats["total_lost"] += bet_amount

        conn.commit()
        conn.close()
        
        # Log user action
        log_user_action(user_id, f"GAME_{game_type.upper()}", f"{'WIN' if won else 'LOSS'} - Bet: {format_sheckles(bet_amount)}, Result: {format_sheckles(win_amount if won else 0)}")
        
    except Exception as e:
        logger.error(f"Database error in update_user_stats: {e}")
        logger.error(traceback.format_exc())

# ==========================================
# 🎮 MODERN UI VIEWS & BUTTONS
# ==========================================

class PvPChallengeView(discord.ui.View):
    """View for PvP challenge requests"""
    def __init__(self, challenger_id, opponent_id, game_type, bet_amount):
        super().__init__(timeout=300)  # 5 minute timeout
        self.challenger_id = challenger_id
        self.opponent_id = opponent_id
        self.game_type = game_type
        self.bet_amount = bet_amount
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in [self.challenger_id, self.opponent_id]:
            await interaction.response.send_message("🚫 This challenge isn't for you!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ ACCEPT", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept_challenge(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("🚫 Only the challenged player can accept!", ephemeral=True)
            return

        await interaction.response.defer()

        # Check both players have enough balance
        challenger = get_user(self.challenger_id)
        opponent = get_user(self.opponent_id)

        if challenger[challenger["mode"]] < self.bet_amount:
            embed = create_casino_embed(
                "❌ Challenge Failed",
                "Challenger doesn't have enough balance!",
                CASINO_THEME["danger"]
            )
            await interaction.message.edit(embed=embed, view=None)
            return

        if opponent[opponent["mode"]] < self.bet_amount:
            embed = create_casino_embed(
                "❌ Challenge Failed", 
                "You don't have enough balance!",
                CASINO_THEME["danger"]
            )
            await interaction.message.edit(embed=embed, view=None)
            return

        # Start the PvP game
        await self.start_pvp_game(interaction)

    @discord.ui.button(label="❌ DECLINE", style=discord.ButtonStyle.danger, emoji="🚫")
    async def decline_challenge(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent_id:
            await interaction.response.send_message("🚫 Only the challenged player can decline!", ephemeral=True)
            return

        try:
            challenger_user = await bot.fetch_user(self.challenger_id)
        except discord.DiscordException:
            challenger_user = discord.Object(id=self.challenger_id) # Placeholder if fetch fails
            challenger_user.display_name = "Unknown Challenger"

        opponent_name = format_user_name_for_pvp(interaction.user)
        challenger_name = format_user_name_for_pvp(challenger_user, self.challenger_id)
        
        embed = create_casino_embed(
            "Challenge Declined",
            f"**{opponent_name}** declined the challenge from **{challenger_name}**",
            CASINO_THEME["warning"],
            interaction.user,
            is_pvp=True
        )
        await interaction.response.edit_message(embed=embed, view=None)

        # Remove from active challenges
        if self.challenger_id in active_challenges:
            del active_challenges[self.challenger_id]

    async def start_pvp_game(self, interaction):
        game_id = f"{self.challenger_id}_{self.opponent_id}_{int(time.time())}"

        # Remove from active challenges
        if self.challenger_id in active_challenges:
            del active_challenges[self.challenger_id]

        if self.game_type == "coinflip":
            view = PvPCoinflipView(self.challenger_id, self.opponent_id, self.bet_amount, game_id)
        elif self.game_type == "dice":
            view = PvPDiceView(self.challenger_id, self.opponent_id, self.bet_amount, game_id)
        else:
            embed = create_casino_embed("❌ Game Not Supported", "This game type isn't available for PvP yet!", CASINO_THEME["danger"])
            await interaction.message.edit(embed=embed, view=None)
            return

        try:
            challenger_user = await bot.fetch_user(self.challenger_id)
            opponent_user = await bot.fetch_user(self.opponent_id)
        except discord.DiscordException:
            embed = create_casino_embed("❌ Error", "Failed to fetch user data.", CASINO_THEME["danger"])
            await interaction.message.edit(embed=embed, view=None)
            return

        challenger_name = format_user_name_for_pvp(challenger_user, self.challenger_id)
        opponent_name = format_user_name_for_pvp(opponent_user, self.opponent_id)
        
        embed = create_casino_embed(
            f"⚔️ PvP {self.game_type.title()} Battle!",
            f"**{challenger_name}** vs **{opponent_name}**\n"
            f"💰 **Stakes:** {format_sheckles(self.bet_amount)} sheckles each\n"
            f"🎯 **Winner takes all:** {format_sheckles(self.bet_amount * 2)} sheckles!",
            CASINO_THEME["premium"],
            challenger_user,
            is_pvp=True
        )
        embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")

        await interaction.message.edit(embed=embed, view=view)
        view.message = interaction.message

        # Store active game
        active_pvp_games[game_id] = {
            "players": [self.challenger_id, self.opponent_id],
            "game_type": self.game_type,
            "bet_amount": self.bet_amount,
            "spectators": []
        }

    async def on_timeout(self):
        embed = create_casino_embed(
            "⏰ Challenge Expired",
            "The challenge request timed out.",
            CASINO_THEME["warning"]
        )
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except:
                pass

        if self.challenger_id in active_challenges:
            del active_challenges[self.challenger_id]

class PvPCoinflipView(discord.ui.View):
    """PvP Coinflip game view"""
    def __init__(self, player1_id, player2_id, bet_amount, game_id):
        super().__init__(timeout=180)
        self.player1_id = player1_id
        self.player2_id = player2_id
        self.bet_amount = bet_amount
        self.game_id = game_id
        self.player1_choice = None
        self.player2_choice = None
        self.choices_made = []
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in [self.player1_id, self.player2_id]:
            await interaction.response.send_message("🚫 You're not part of this game! Use `!spectate` to watch.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔴 HEADS", style=discord.ButtonStyle.danger, emoji="🪙")
    async def heads_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.make_choice(interaction, "heads")

    @discord.ui.button(label="⚫ TAILS", style=discord.ButtonStyle.secondary, emoji="🪙")
    async def tails_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.make_choice(interaction, "tails")

    async def make_choice(self, interaction: discord.Interaction, choice):
        if interaction.user.id in self.choices_made:
            await interaction.response.send_message("🚫 You've already made your choice!", ephemeral=True)
            return

        await interaction.response.defer()

        self.choices_made.append(interaction.user.id)

        if interaction.user.id == self.player1_id:
            self.player1_choice = choice
        else:
            self.player2_choice = choice

        if len(self.choices_made) == 1:
            # First player chose
            try:
                player_user = await bot.fetch_user(interaction.user.id)
            except discord.DiscordException:
                player_user = discord.Object(id=interaction.user.id)
                player_user.display_name = "Unknown Player"

            player_name = format_user_name_for_pvp(player_user, interaction.user.id)
            
            embed = create_casino_embed(
                "⚔️ PvP Coinflip - Waiting",
                f"**{player_name}** has locked in their choice!\n"
                f"Waiting for the other player to choose...",
                CASINO_THEME["info"],
                player_user,
                is_pvp=True
            )
            await interaction.message.edit(embed=embed, view=self)
        else:
            # Both players chose - resolve game
            await self.resolve_game(interaction)

    async def resolve_game(self, interaction):
        # Disable buttons
        for child in self.children:
            child.disabled = True

        frames = [
            "🪙 The coin is spinning...",
            "⚡ Higher and higher...",
            "💫 Coming down now...",
            "🎯 The result is..."
        ]

        await animate_loading(interaction.message, frames, 1.0)

        # Flip the coin
        result = random.choice(["heads", "tails"])

        try:
            player1_user = await bot.fetch_user(self.player1_id)
            player2_user = await bot.fetch_user(self.player2_id)
        except discord.DiscordException:
            embed = create_casino_embed("❌ Error", "Failed to fetch user data.", CASINO_THEME["danger"])
            await interaction.message.edit(embed=embed, view=self)
            return

        player1 = get_user(self.player1_id)
        player2 = get_user(self.player2_id)

        # Deduct bets from both players
        player1[player1["mode"]] -= self.bet_amount
        player2[player2["mode"]] -= self.bet_amount

        # Determine winner
        winner = None
        loser = None
        winner_user = None
        loser_user = None

        if self.player1_choice == result and self.player2_choice != result:
            winner = player1
            loser = player2
            winner_user = player1_user
            loser_user = player2_user
        elif self.player2_choice == result and self.player1_choice != result:
            winner = player2
            loser = player1
            winner_user = player2_user
            loser_user = player1_user

        player1_name = format_user_name_for_pvp(player1_user, self.player1_id)
        player2_name = format_user_name_for_pvp(player2_user, self.player2_id)
        
        if winner:
            # Winner gets both bets
            winner[winner["mode"]] += (self.bet_amount * 2)
            winner_name = format_user_name_for_pvp(winner_user)

            embed = create_casino_embed(
                "🎉 PvP WINNER!",
                f"🪙 **The coin landed on {result.upper()}!**\n\n"
                f"🏆 **{winner_name}** wins!\n"
                f"💰 Won **{format_sheckles(self.bet_amount * 2)} sheckles**!\n\n"
                f"📊 **Choices:**\n"
                f"• {player1_name}: {self.player1_choice}\n"
                f"• {player2_name}: {self.player2_choice}",
                CASINO_THEME["success"],
                winner_user,
                is_pvp=True
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
        else:
            # Tie - return bets
            player1[player1["mode"]] += self.bet_amount
            player2[player2["mode"]] += self.bet_amount

            embed = create_casino_embed(
                "🤝 TIE GAME!",
                f"🪙 **The coin landed on {result.upper()}!**\n\n"
                f"Both players chose **{result}** - it's a tie!\n"
                f"💰 Bets returned to both players.\n\n"
                f"📊 **Choices:**\n"
                f"• {player1_name}: {self.player1_choice}\n"
                f"• {player2_name}: {self.player2_choice}",
                CASINO_THEME["warning"],
                player1_user,
                is_pvp=True
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")

        save_data()
        await interaction.message.edit(embed=embed, view=self)

        # Clean up active game
        if self.game_id in active_pvp_games:
            del active_pvp_games[self.game_id]

class PvPDiceView(discord.ui.View):
    """PvP Dice rolling game view"""
    def __init__(self, player1_id, player2_id, bet_amount, game_id):
        super().__init__(timeout=180)
        self.player1_id = player1_id
        self.player2_id = player2_id
        self.bet_amount = bet_amount
        self.game_id = game_id
        self.rolls_made = []
        self.player1_roll = None
        self.player2_roll = None
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in [self.player1_id, self.player2_id]:
            await interaction.response.send_message("🚫 You're not part of this game!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🎲ROLL DICE", style=discord.ButtonStyle.primary, emoji="🎯")
    async def roll_dice(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in self.rolls_made:
            await interaction.response.send_message("🚫 You've already rolled!", ephemeral=True)
            return

        await interaction.response.defer()

        roll = random.randint(1, 6)
        self.rolls_made.append(interaction.user.id)

        if interaction.user.id == self.player1_id:
            self.player1_roll = roll
        else:
            self.player2_roll = roll

        if len(self.rolls_made) == 1:
            try:
                player_user = await bot.fetch_user(interaction.user.id)
            except discord.DiscordException:
                player_user = discord.Object(id=interaction.user.id)
                player_user.display_name = "Unknown Player"

            player_name = format_user_name_for_pvp(player_user, interaction.user.id)
            
            embed = create_casino_embed(
                "⚔️ PvP Dice - Waiting",
                f"**{player_name}** has rolled!\n"
                f"Waiting for the other player to roll...",
                CASINO_THEME["info"],
                player_user,
                is_pvp=True
            )
            await interaction.message.edit(embed=embed, view=self)
        else:
            await self.resolve_game(interaction)

    async def resolve_game(self, interaction):
        for child in self.children:
            child.disabled = True

        frames = [
            "🎲 Both dice are rolling...",
            "⚡ Tumbling through the air...",
            "🌟 Coming to a stop...",
            "🎯 Results revealed!"
        ]

        await animate_loading(interaction.message, frames, 1.0)

        try:
            player1_user = await bot.fetch_user(self.player1_id)
            player2_user = await bot.fetch_user(self.player2_id)
        except discord.DiscordException:
            embed = create_casino_embed("❌ Error", "Failed to fetch user data.", CASINO_THEME["danger"])
            await interaction.message.edit(embed=embed, view=self)
            return

        player1 = get_user(self.player1_id)
        player2 = get_user(self.player2_id)

        # Deduct bets
        player1[player1["mode"]] -= self.bet_amount
        player2[player2["mode"]] -= self.bet_amount

        player1_name = format_user_name_for_pvp(player1_user, self.player1_id)
        player2_name = format_user_name_for_pvp(player2_user, self.player2_id)
        
        if self.player1_roll > self.player2_roll:
            # Player 1 wins
            player1[player1["mode"]] += (self.bet_amount * 2)
            embed = create_casino_embed(
                "🎉 PvP DICE WINNER!",
                f"🎲 **{player1_name}** rolled **{self.player1_roll}**!\n"
                f"🎲 **{player2_name}** rolled **{self.player2_roll}**!\n\n"
                f"🏆 **{player1_name}** wins **{format_sheckles(self.bet_amount * 2)} sheckles**!",
                CASINO_THEME["success"],
                player1_user,
                is_pvp=True
            )
        elif self.player2_roll > self.player1_roll:
            # Player 2 wins
            player2[player2["mode"]] += (self.bet_amount * 2)
            embed = create_casino_embed(
                "🎉 PvP DICE WINNER!",
                f"🎲 **{player1_name}** rolled **{self.player1_roll}**!\n"
                f"🎲 **{player2_name}** rolled **{self.player2_roll}**!\n\n"
                f"🏆 **{player2_name}** wins **{format_sheckles(self.bet_amount * 2)} sheckles**!",
                CASINO_THEME["success"],
                player2_user,
                is_pvp=True
            )
        else:
            # Tie - return bets
            player1[player1["mode"]] += self.bet_amount
            player2[player2["mode"]] += self.bet_amount
            embed = create_casino_embed(
                "🤝 TIE GAME!",
                f"🎲 Both players rolled **{self.player1_roll}**!\n"
                f"💰 It's a tie! Bets returned.",
                CASINO_THEME["warning"],
                player1_user,
                is_pvp=True
            )

        embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
        save_data()
        await interaction.message.edit(embed=embed, view=self)

        if self.game_id in active_pvp_games:
            del active_pvp_games[self.game_id]

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

class GameView(discord.ui.View):
    """Base class for game UI interactions"""
    def __init__(self, user_id, timeout=60):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.game_active = True
        self.message: Optional[discord.Message] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("🚫 This isn't your game!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if hasattr(self, 'message') and self.message:
            for child in self.children:
                child.disabled = True
            embed = create_casino_embed("⏰ Game Timeout", "Game session expired", CASINO_THEME["warning"])
            try:
                await self.message.edit(embed=embed, view=self)
            except:
                pass

class CoinflipView(GameView):
    def __init__(self, user_id, bet_amount):
        super().__init__(user_id)
        self.bet_amount = bet_amount
        self.choice = None

    @discord.ui.button(label="🔴 HEADS", style=discord.ButtonStyle.danger, emoji="🪙")
    async def heads_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "heads"
        await self.play_coinflip(interaction)

    @discord.ui.button(label="⚫ TAILS", style=discord.ButtonStyle.secondary, emoji="🪙")
    async def tails_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "tails"
        await self.play_coinflip(interaction)

    async def play_coinflip(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # Disable buttons
        for child in self.children:
            child.disabled = True

        # Animation frames
        frames = [
            "🪙 The coin is spinning...",
            "🌟 Higher... higher...",
            "💫 It's coming down...",
            "🎯 Almost there..."
        ]

        await animate_loading(interaction.message, frames, 1.0)

        user = get_user(interaction.user.id)
        win_rate = get_user_win_rate(interaction.user.id)
        game_odds = ODDS_CONFIG["game_multipliers"]["coinflip"]

        # House-favoring logic
        result = random.choice(["heads", "tails"])
        player_wins = (result == self.choice) and (random.random() < win_rate * game_odds["base_odds"])

        user["bets"] += 1

        if player_wins:
            user["wins"] += 1
            winnings = int(self.bet_amount * game_odds["payout"])
            user[user["mode"]] += winnings

            embed = create_casino_embed(
                "🎉 WINNER!",
                f"🪙 The coin landed on **{result.upper()}**!\n"
                f"✨ You won **{format_sheckles(winnings)} sheckles**!",
                CASINO_THEME["success"],
                interaction.user
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
            update_user_stats(str(interaction.user.id), "coinflip", self.bet_amount, winnings, True)
        else:
            user["losses"] += 1
            user[user["mode"]] -= self.bet_amount

            embed = create_casino_embed(
                "💸 You Lost",
                f"🪙 The coin landed on **{result.upper()}**\n"
                f"💔 You lost **{format_sheckles(self.bet_amount)} sheckles**",
                CASINO_THEME["danger"],
                interaction.user
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
            update_user_stats(str(interaction.user.id), "coinflip", self.bet_amount, 0, False)

        embed.add_field(name="💰 New Balance", value=f"{format_sheckles(user[user['mode']])} sheckles", inline=True)
        save_data()

        await interaction.message.edit(embed=embed, view=self)

class BlackjackView(GameView):
    def __init__(self, user_id, bet_amount):
        super().__init__(user_id)
        self.bet_amount = bet_amount
        self.deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4
        random.shuffle(self.deck)
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.game_over = False

    def hand_value(self, hand):
        total = sum(hand)
        aces = hand.count(11)
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    def format_hand(self, hand, hide_first=False):
        def card_to_display(card):
            if card == 11:
                return "A"
            elif card == 10:
                return random.choice(["10", "J", "Q", "K"])
            else:
                return str(card)

        if hide_first:
            visible_cards = [card_to_display(card) for card in hand[1:]]
            return f"🎴 + {' + '.join(visible_cards)}"

        display_cards = [card_to_display(card) for card in hand]
        return " + ".join(display_cards)

    @discord.ui.button(label="🎯 HIT", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        self.player_hand.append(self.deck.pop())
        player_value = self.hand_value(self.player_hand)

        if player_value > 21:
            await self.end_game(interaction, "bust")
        else:
            await self.update_game_display(interaction)

    @discord.ui.button(label="🛑 STAND", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.end_game(interaction, "stand")

    async def update_game_display(self, interaction):
        player_value = self.hand_value(self.player_hand)

        embed = create_casino_embed(
            "🃏 Blackjack Game",
            "",
            CASINO_THEME["info"],
            interaction.user
        )
        embed.add_field(
            name="🎴 Your Hand", 
            value=f"{self.format_hand(self.player_hand)} = **{player_value}**", 
            inline=False
        )
        embed.add_field(
            name="🎭 Dealer's Hand", 
            value=f"{self.format_hand(self.dealer_hand, True)} = **?**", 
            inline=False
        )
        embed.add_field(
            name="💰 Bet", 
            value=f"**{format_sheckles(self.bet_amount)} sheckles**", 
            inline=True
        )
        embed.set_thumbnail(url="https://media.giphy.com/media/3oriO6qJiXajN0TyDu/gif")

        await interaction.message.edit(embed=embed, view=self)

    async def end_game(self, interaction, reason):
        for child in self.children:
            child.disabled = True

        user = get_user(interaction.user.id)
        win_rate = get_user_win_rate(interaction.user.id)
        game_odds = ODDS_CONFIG["game_multipliers"]["blackjack"]

        # Dealer plays
        while self.hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())

        player_final = self.hand_value(self.player_hand)
        dealer_final = self.hand_value(self.dealer_hand)

        user["bets"] += 1

        # Determine winner with house edge
        if reason == "bust":
            # Player busted - house always wins
            user["losses"] += 1
            user[user["mode"]] -= self.bet_amount
            result_msg = f"💥 BUST! You went over 21 and lost **{format_sheckles(self.bet_amount)} sheckles**"
            embed_color = CASINO_THEME["danger"]
            thumbnail_url = "https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif"
            update_user_stats(str(interaction.user.id), "blackjack", self.bet_amount, 0, False)
        else:
            # Apply house edge fairly
            house_edge_roll = random.random()
            win_chance = win_rate * game_odds["base_odds"]

            # Determine natural game outcome first
            if dealer_final > 21:
                # Dealer busted - player should win (unless house edge kicks in)
                if house_edge_roll < win_chance:
                    winnings = int(self.bet_amount * game_odds["blackjack_bonus"])
                    user["wins"] += 1
                    user[user["mode"]] += winnings
                    result_msg = f"🎉 Dealer busted! You won **{format_sheckles(winnings)} sheckles**!"
                    embed_color = CASINO_THEME["success"]
                    thumbnail_url = "https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif"
                    update_user_stats(str(interaction.user.id), "blackjack", self.bet_amount, winnings, True)
                else:
                    user["losses"] += 1
                    user[user["mode"]] -= self.bet_amount
                    result_msg = f"💸 House edge! Despite dealer bust, you lost **{format_sheckles(self.bet_amount)} sheckles**"
                    embed_color = CASINO_THEME["danger"]
                    thumbnail_url = "https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif"
                    update_user_stats(str(interaction.user.id), "blackjack", self.bet_amount, 0, False)
            elif player_final > dealer_final:
                # Player has higher hand - should win (unless house edge kicks in)
                if house_edge_roll < win_chance:
                    winnings = int(self.bet_amount * game_odds["blackjack_bonus"])
                    user["wins"] += 1
                    user[user["mode"]] += winnings
                    result_msg = f"🎉 You win with {player_final}! Won **{format_sheckles(winnings)} sheckles**!"
                    embed_color = CASINO_THEME["success"]
                    thumbnail_url = "https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif"
                    update_user_stats(str(interaction.user.id), "blackjack", self.bet_amount, winnings, True)
                else:
                    user["losses"] += 1
                    user[user["mode"]] -= self.bet_amount
                    result_msg = f"💸 House edge! Despite higher hand, you lost **{format_sheckles(self.bet_amount)} sheckles**"
                    embed_color = CASINO_THEME["danger"]
                    thumbnail_url = "https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif"
                    update_user_stats(str(interaction.user.id), "blackjack", self.bet_amount, 0, False)
            elif player_final == dealer_final:
                # Tie - always push (return bet)
                result_msg = f"🤝 Push! Both got {player_final}. Your bet is returned."
                embed_color = CASINO_THEME["warning"]
                thumbnail_url = "https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif"
                update_user_stats(str(interaction.user.id), "blackjack", self.bet_amount, self.bet_amount, True)
            else:
                # Dealer has higher hand - player loses
                user["losses"] += 1
                user[user["mode"]] -= self.bet_amount
                result_msg = f"😞 Dealer wins with {dealer_final}! Lost **{format_sheckles(self.bet_amount)} sheckles**"
                embed_color = CASINO_THEME["danger"]
                thumbnail_url = "https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif"
                update_user_stats(str(interaction.user.id), "blackjack", self.bet_amount, 0, False)

        save_data()

        embed = create_casino_embed("🃏 Game Over", "", embed_color, interaction.user)
        embed.add_field(
            name="🎴 Your Final Hand", 
            value=f"{self.format_hand(self.player_hand)} = **{player_final}**", 
            inline=False
        )
        embed.add_field(
            name="🎭 Dealer's Final Hand", 
            value=f"{self.format_hand(self.dealer_hand)} = **{dealer_final}**", 
            inline=False
        )
        embed.add_field(name="📊 Result", value=result_msg, inline=False)
        embed.add_field(name="💰 New Balance", value=f"{format_sheckles(user[user['mode']])} sheckles", inline=True)
        embed.set_thumbnail(url=thumbnail_url)

        await interaction.message.edit(embed=embed, view=self)

class RouletteView(GameView):
    def __init__(self, user_id, bet_amount):
        super().__init__(user_id)
        self.bet_amount = bet_amount
        self.choice = None

    @discord.ui.button(label="🔴 RED", style=discord.ButtonStyle.danger, emoji="🎯")
    async def red_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "red"
        await self.spin_roulette(interaction)

    @discord.ui.button(label="⚫ BLACK", style=discord.ButtonStyle.secondary, emoji="🎯")
    async def black_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "black"
        await self.spin_roulette(interaction)

    @discord.ui.button(label="🟢 GREEN", style=discord.ButtonStyle.success, emoji="🎯")
    async def green_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = "green"
        await self.spin_roulette(interaction)

    async def spin_roulette(self, interaction: discord.Interaction):
        await interaction.response.defer()

        for child in self.children:
            child.disabled = True

        frames = [
            "🎰 The wheel is spinning...",
            "⚡ Round and round it goes...",
            "💫 Slowing down...",
            "🎯 Where will it land?"
        ]

        await animate_loading(interaction.message, frames, 1.2)

        user = get_user(interaction.user.id)
        win_rate = get_user_win_rate(interaction.user.id)
        game_odds = ODDS_CONFIG["game_multipliers"]["roulette"]

        roll = random.randint(0, 36)

        if roll == 0:
            outcome = "green"
        elif roll % 2 == 0:
            outcome = "red"
        else:
            outcome = "black"

        user["bets"] += 1

        # House-favoring logic
        if outcome == self.choice:
            if self.choice == "green":
                player_wins = random.random() < win_rate * game_odds["green_odds"]
                payout = game_odds["green_payout"]
            else:
                player_wins = random.random() < win_rate * game_odds["red_black_odds"]
                payout = game_odds["red_black_payout"]

            if player_wins:
                winnings = int(self.bet_amount * payout)
                user[user["mode"]] += winnings
                user["wins"] += 1

                embed = create_casino_embed(
                    "🎉 WINNER!",
                    f"🎯 The ball landed on **{roll} ({outcome.upper()})**!\n"
                    f"💰 You won **{format_sheckles(winnings)} sheckles**!",
                    CASINO_THEME["success"],
                    interaction.user
                )
                embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
                update_user_stats(str(interaction.user.id), "roulette", self.bet_amount, winnings, True)
            else:
                # House edge kicks in even on "winning" numbers
                user[user["mode"]] -= self.bet_amount
                user["losses"] += 1

                embed = create_casino_embed(
                    "💸 House Edge",
                    f"🎯 The ball landed on **{roll} ({outcome.upper()})**\n"
                    f"🎰 House advantage! You lost **{format_sheckles(self.bet_amount)} sheckles**",
                    CASINO_THEME["danger"],
                    interaction.user
                )
                embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
                update_user_stats(str(interaction.user.id), "roulette", self.bet_amount, 0, False)
        else:
            user[user["mode"]] -= self.bet_amount
            user["losses"] += 1

            embed = create_casino_embed(
                "💸 You Lost",
                f"🎯 The ball landed on **{roll} ({outcome.upper()})**\n"
                f"💔 You lost **{format_sheckles(self.bet_amount)} sheckles**",
                CASINO_THEME["danger"],
                interaction.user
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
            update_user_stats(str(interaction.user.id), "roulette", self.bet_amount, 0, False)

        embed.add_field(name="💰 New Balance", value=f"{format_sheckles(user[user['mode']])} sheckles", inline=True)
        save_data()

        await interaction.message.edit(embed=embed, view=self)

# ==========================================
# 🎮 MODERN GAMBLING COMMANDS
# ==========================================

@bot.command(aliases=['cf'])
@commands.cooldown(1, 3, commands.BucketType.user)
async def coinflip(ctx, amount: str = None):
    """🪙 Flip a coin! Choose heads or tails with interactive buttons"""
    if amount is None:
        embed = create_casino_embed(
            "❌ Missing Amount",
            "**Usage:** `!coinflip <amount>`\n**Example:** `!coinflip 10T`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if not check_rate_limit(ctx.author.id, "coinflip"):
        embed = create_casino_embed(
            "⏳ Slow Down!",
            "You're flipping too fast! Wait a moment.",
            CASINO_THEME["warning"]
        )
        return await ctx.send(embed=embed)

    user = get_user(ctx.author.id)

    try:
        if amount.lower() == "all":
            amt = user[user["mode"]]
        else:
            amt = parse_sheckles(amount)
    except:
        embed = create_casino_embed(
            "❌ Invalid Amount",
            "Use valid number like `5T`, `1M`, etc. or `all`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if user[user["mode"]] < amt or amt <= 0:
        embed = create_casino_embed(
            "💸 Insufficient Funds",
            f"You have **{format_sheckles(user[user['mode']])} sheckles**",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    embed = create_casino_embed(
        "🪙 Coinflip Game",
        f"**Bet Amount:** {format_sheckles(amt)} sheckles\n"
        f"**Your Balance:** {format_sheckles(user[user['mode']])} sheckles\n\n"
        f"Choose your side by clicking a button below!",
        CASINO_THEME["info"],
        ctx.author
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")

    view = CoinflipView(ctx.author.id, amt)
    message = await ctx.send(embed=embed, view=view)
    view.message = message

@bot.command(aliases=['bj'])
@commands.cooldown(1, 5, commands.BucketType.user)
async def blackjack(ctx, amount: str = None):
    """🃏 Play interactive blackjack against the dealer!"""
    if amount is None:
        embed = create_casino_embed(
            "❌ Missing Amount",
            "**Usage:** `!blackjack <amount>`\n**Example:** `!blackjack 2T`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if not check_rate_limit(ctx.author.id, "blackjack"):
        embed = create_casino_embed(
            "⏳ Slow Down!",
            "Take a break from the tables!",
            CASINO_THEME["warning"]
        )
        return await ctx.send(embed=embed)

    user = get_user(ctx.author.id)

    try:
        if amount.lower() == "all":
            bet = user[user["mode"]]
        else:
            bet = parse_sheckles(amount)
    except:
        embed = create_casino_embed(
            "❌ Invalid Bet",
            "Use a valid number like `5T`, `1M`, etc. or `all`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if bet <= 0 or user[user["mode"]] < bet:
        embed = create_casino_embed(
            "💸 Insufficient Funds",
            f"You have **{format_sheckles(user[user['mode']])}**",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    view = BlackjackView(ctx.author.id, bet)

    embed = create_casino_embed(
        "🃏 Blackjack Game",
        "",
        CASINO_THEME["info"],
        ctx.author
    )
    embed.add_field(
        name="🎴 Your Hand", 
        value=f"{view.format_hand(view.player_hand)} = **{view.hand_value(view.player_hand)}**", 
        inline=False
    )
    embed.add_field(
        name="🎭 Dealer's Hand", 
        value=f"{view.format_hand(view.dealer_hand, True)} = **?**", 
        inline=False
    )
    embed.add_field(
        name="💰 Bet", 
        value=f"**{format_sheckles(bet)} sheckles**", 
        inline=True
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3oriO6qJiXajN0TyDu/gif")

    message = await ctx.send(embed=embed, view=view)
    view.message = message

@bot.command()
@commands.cooldown(1, 3, commands.BucketType.user)
async def roulette(ctx, amount: str = None):
    """🎯 Play roulette! Bet on red, black, or green with buttons"""
    if amount is None:
        embed = create_casino_embed(
            "❌ Missing Amount",
            "**Usage:** `!roulette <amount>`\n**Example:** `!roulette 1T`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if not check_rate_limit(ctx.author.id, "roulette"):
        embed = create_casino_embed(
            "⏳ Slow Down!",
            "The wheel needs time to cool down!",
            CASINO_THEME["warning"]
        )
        return await ctx.send(embed=embed)

    user = get_user(ctx.author.id)

    try:
        if amount.lower() == "all":
            amt = user[user["mode"]]
        else:
            amt = parse_sheckles(amount)
    except:
        embed = create_casino_embed(
            "❌ Invalid Amount",
            "Use amount like `10T`, `500M`, etc. or `all`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if user[user["mode"]] < amt or amt <= 0:
        embed = create_casino_embed(
            "💸 Insufficient Funds",
            f"You only have **{format_sheckles(user[user['mode']])}**",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    embed = create_casino_embed(
        "🎯 Roulette Wheel",
        f"**Bet Amount:** {format_sheckles(amt)} sheckles\n"
        f"**Your Balance:** {format_sheckles(user[user['mode']])} sheckles\n\n"
        f"🔴 **Red/Black:** Lower risk, moderate payout\n"
        f"🟢 **Green:** High risk, massive payout!",
        CASINO_THEME["info"],
        ctx.author
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")

    view = RouletteView(ctx.author.id, amt)
    message = await ctx.send(embed=embed, view=view)
    view.message = message

@bot.command()
@commands.cooldown(1, 3, commands.BucketType.user)
async def slot(ctx, amount: str = None):
    """🎰 Play the slot machine! Match 3 symbols to win big!"""
    if amount is None:
        embed = create_casino_embed(
            "❌ Missing Amount",
            "**Usage:** `!slot <amount>`\n**Example:** `!slot 5T`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if not check_rate_limit(ctx.author.id, "slot"):
        embed = create_casino_embed(
            "⏳ Slow Down!",
            "The slots are overheating!",
            CASINO_THEME["warning"]
        )
        return await ctx.send(embed=embed)

    user = get_user(ctx.author.id)

    try:
        if amount.lower() == "all":
            amt = user[user["mode"]]
        else:
            amt = parse_sheckles(amount)
    except:
        embed = create_casino_embed(
            "❌ Invalid Amount",
            "Use valid number like `5T`, `1M`, etc. or `all`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if user[user["mode"]] < amt or amt <= 0:
        embed = create_casino_embed(
            "💸 Insufficient Funds",
            f"You have **{format_sheckles(user[user['mode']])} sheckles**",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    # Create initial message
    embed = create_casino_embed(
        "🎰 Slot Machine",
        "🎲 The reels are spinning...",
        CASINO_THEME["info"],
        ctx.author
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")

    message = await ctx.send(embed=embed)

    # Animation
    frames = [
        "🎰 ░ ░ ░",
        "🎰 🍒 ░ ░",
        "🎰 🍒 🍋 ░",
        "🎰 🍒 🍋 🍇",
        "🎯 Rolling final results..."
    ]

    await animate_loading(message, frames, 1.0)

    user["bets"] += 1
    win_rate = get_user_win_rate(ctx.author.id)
    game_odds = ODDS_CONFIG["game_multipliers"]["slot"]

    symbols = ["🍒", "🍋", "🍇", "🔔", "⭐", "💎"]
    result = [random.choice(symbols) for _ in range(3)]

    # Calculate jackpot probability
    if result[0] == result[1] == result[2]:  # Jackpot
        player_wins = random.random() < win_rate * game_odds["jackpot_odds"]
        if player_wins:
            winnings = int(amt * game_odds["jackpot_payout"])
            user[user["mode"]] += winnings
            user["wins"] += 1

            embed = create_casino_embed(
                "🎰 JACKPOT!",
                f"**{''.join(result)}**\n\n💰 You won **{format_sheckles(winnings)}** sheckles!",
                CASINO_THEME["success"],
                ctx.author
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
            update_user_stats(str(ctx.author.id), "slot", amt, winnings, True)
        else:
            user[user["mode"]] -= amt
            user["losses"] += 1

            embed = create_casino_embed(
                "💸 So Close!",
                f"**{''.join(result)}**\n\n🎯 Jackpot symbols but luck wasn't on your side!\n💸 Lost **{format_sheckles(amt)} sheckles**",
                CASINO_THEME["danger"],
                ctx.author
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
            update_user_stats(str(ctx.author.id), "slot", amt, 0, False)
    elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:  # Partial match
        player_wins = random.random() < win_rate * game_odds["partial_odds"]
        if player_wins:
            winnings = int(amt * game_odds["partial_payout"])
            user[user["mode"]] += winnings
            user["wins"] += 1

            embed = create_casino_embed(
                "🎉 Nice!",
                f"**{''.join(result)}**\n\n✨ Partial match! Won **{format_sheckles(winnings)}** sheckles!",
                CASINO_THEME["success"],
                ctx.author
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
            update_user_stats(str(ctx.author.id), "slot", amt, winnings, True)
        else:
            user[user["mode"]] -= amt
            user["losses"] += 1

            embed = create_casino_embed(
                "💔 Close Call",
                f"**{''.join(result)}**\n\n🎰 Match but not quite enough!\n💸 Lost **{format_sheckles(amt)} sheckles**",
                CASINO_THEME["danger"],
                ctx.author
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
            update_user_stats(str(ctx.author.id), "slot", amt, 0, False)
    else:  # Loss
        user[user["mode"]] -= amt
        user["losses"] += 1

        embed = create_casino_embed(
            "💸 No Match",
            f"**{''.join(result)}**\n\n💔 You lost **{format_sheckles(amt)} sheckles**",
            CASINO_THEME["danger"],
            ctx.author
        )
        embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
        update_user_stats(str(ctx.author.id), "slot", amt, 0, False)

    embed.add_field(name="💰 New Balance", value=f"{format_sheckles(user[user['mode']])} sheckles", inline=True)
    save_data()

    await message.edit(embed=embed)

@bot.command()
@commands.cooldown(1, 3, commands.BucketType.user)
async def dice(ctx, amount: str = None):
    """🎲 Roll dice! Bet on the outcome (1-6)"""
    if amount is None:
        embed = create_casino_embed(
            "❌ Missing Amount",
            "**Usage:** `!dice <amount>`\n**Example:** `!dice 10T`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if not check_rate_limit(ctx.author.id, "dice"):
        embed = create_casino_embed(
            "⏳ Slow Down!",
            "The dice need a rest!",
            CASINO_THEME["warning"]
        )
        return await ctx.send(embed=embed)

    user = get_user(ctx.author.id)

    try:
        if amount.lower() == "all":
            amt = user[user["mode"]]
        else:
            amt = parse_sheckles(amount)
    except:
        embed = create_casino_embed(
            "❌ Invalid Amount",
            "Use valid number or 'all'",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if user[user["mode"]] < amt or amt <= 0:
        embed = create_casino_embed(
            "💸 Invalid Bet",
            "Check your balance",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    # Create initial message
    embed = create_casino_embed(
        "🎲 Rolling Dice",
        "🎯 The dice are tumbling...",
        CASINO_THEME["info"],
        ctx.author
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")

    message = await ctx.send(embed=embed)

    frames = [
        "🎲 Rolling... ⚡",
        "🎲 Still rolling... 💫",
        "🎲 Almost there... 🌟",
        "🎯 Final result coming..."
    ]

    await animate_loading(message, frames, 0.8)

    user["bets"] += 1
    game_odds = ODDS_CONFIG["game_multipliers"]["dice"]

    roll = random.randint(1, 6)

    # Balanced dice game - no house edge, fair odds based on roll
    if roll == 6:  # Jackpot - 70% win chance
        if random.random() < 0.70:
            multiplier = game_odds["jackpot_payout"]
            winnings = int(amt * multiplier)
            user[user["mode"]] += winnings
            user["wins"] += 1

            embed = create_casino_embed(
                "🎰 JACKPOT!",
                f"🎲 Rolled a **{roll}**!\n💰 Won **{format_sheckles(winnings)} sheckles**!",
                CASINO_THEME["success"],
                ctx.author
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
            update_user_stats(str(ctx.author.id), "dice", amt, winnings, True)
        else:
            user[user["mode"]] -= amt
            user["losses"] += 1

            embed = create_casino_embed(
                "💸 Unlucky Six!",
                f"🎲 Rolled a **{roll}** but luck wasn't on your side!\n💸 Lost **{format_sheckles(amt)} sheckles**",
                CASINO_THEME["danger"],
                ctx.author
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
            update_user_stats(str(ctx.author.id), "dice", amt, 0, False)
    elif roll >= 4:  # Good roll - 55% win chance
        if random.random() < 0.55:
            multiplier = game_odds["good_payout"]
            winnings = int(amt * multiplier)
            user[user["mode"]] += winnings
            user["wins"] += 1

            embed = create_casino_embed(
                "✅ Good Roll!",
                f"🎲 Rolled a **{roll}**!\n💰 Won **{format_sheckles(winnings)} sheckles**!",
                CASINO_THEME["success"],
                ctx.author
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
            update_user_stats(str(ctx.author.id), "dice", amt, winnings, True)
        else:
            user[user["mode"]] -= amt
            user["losses"] += 1

            embed = create_casino_embed(
                "💸 Close Call!",
                f"🎲 Rolled a **{roll}** but not quite enough!\n💸 Lost **{format_sheckles(amt)} sheckles**",
                CASINO_THEME["danger"],
                ctx.author
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
            update_user_stats(str(ctx.author.id), "dice", amt, 0, False)
    else:  # Rolls 1-3 = Always lose
        user["losses"] += 1
        user[user["mode"]] -= amt

        embed = create_casino_embed(
            "💸 Too Low!",
            f"🎲 Rolled a **{roll}**\n💔 Lost **{format_sheckles(amt)} sheckles**",
            CASINO_THEME["danger"],
            ctx.author
        )
        embed.set_thumbnail(url="https://media.giphy.com/media/3o7527pa7qs9kCG78A/giphy.gif")
        update_user_stats(str(ctx.author.id), "dice", amt, 0, False)

    embed.add_field(name="💰 New Balance", value=f"{format_sheckles(user[user['mode']])} sheckles", inline=True)
    save_data()

    await message.edit(embed=embed)

# ==========================================
# 📊 BALANCE & ACCOUNT COMMANDS
# ==========================================

@bot.command(aliases=['bal'])
async def balance(ctx, member: discord.Member = None):
    """💰 Check balance (your own or someone else's)"""
    target = member or ctx.author
    user = get_user(target.id)

    theme_color = CASINO_THEME["premium"] if "vip_theme" in user["cosmetics"]["badges"] else CASINO_THEME["primary"]

    embed = create_casino_embed(
        f"{target.display_name}'s Casino Vault",
        "",
        theme_color,
        target
    )

    embed.add_field(
        name="🎯 Trial Balance",
        value=f"**{format_sheckles(user['trial'])}** sheckles",
        inline=True
    )
    embed.add_field(
        name="💎 Premium Balance", 
        value=f"**{format_sheckles(user['premium'])}** sheckles",
        inline=True
    )
    embed.add_field(
        name="🎮 Current Mode",
        value=f"**{user['mode'].title()}**",
        inline=True
    )

    # Show badges if any
    if user["cosmetics"]["badges"]:
        badges_display = " ".join([f"🏅" for _ in user["cosmetics"]["badges"]])
        embed.set_footer(text=f"{FOOTER_TEXT} | {badges_display}")

    embed.set_thumbnail(url=target.display_avatar.url)

    await ctx.send(embed=embed)

@bot.command()
async def switch(ctx):
    """🔁 Switch between trial and premium balance"""
    user = get_user(ctx.author.id)
    user["mode"] = "premium" if user["mode"] == "trial" else "trial"
    save_data()

    embed = create_casino_embed(
        "Balance Switched!",
        f"You are now using your **{user['mode'].title()}** balance.\n"
        f"**Current Balance:** {format_sheckles(user[user['mode']])} sheckles",
        CASINO_THEME["info"],
        ctx.author
    )
    await ctx.send(embed=embed)

# ==========================================
# 🎁 DAILY REWARDS SYSTEM
# ==========================================

@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)
async def claimdaily(ctx):
    """🎁 Claim your daily reward (24 hour cooldown)"""
    user = get_user(ctx.author.id)
    now = time.time()

    if now - user["last_daily"] < 86400:  # 24 hours
        next_claim = user["last_daily"] + 86400
        embed = create_casino_embed(
            "⏳ Already Claimed!",
            f"Come back <t:{int(next_claim)}:R> for your next daily reward!",
            CASINO_THEME["warning"],
            ctx.author
        )
        return await ctx.send(embed=embed)

    reward = 50_000_000_000_000  # 50T
    user["trial"] += reward
    user["last_daily"] = now
    save_data()

    embed = create_casino_embed(
        "Daily Reward Claimed!",
        f"🎉 You received **{format_sheckles(reward)} sheckles**!\n"
        f"💰 New Trial Balance: **{format_sheckles(user['trial'])} sheckles**",
        CASINO_THEME["success"],
        ctx.author
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
    await ctx.send(embed=embed)

@bot.command()
@commands.cooldown(1, 5, commands.BucketType.user)
async def claimweekly(ctx):
    """🎉 Claim your weekly reward (7 day cooldown)"""
    user = get_user(ctx.author.id)
    now = time.time()

    if now - user["last_weekly"] < 604800:  # 7 days
        next_claim = user["last_weekly"] + 604800
        embed = create_casino_embed(
            "⏳ Already Claimed!",
            f"Come back <t:{int(next_claim)}:R> for your next weekly reward!",
            CASINO_THEME["warning"],
            ctx.author
        )
        return await ctx.send(embed=embed)

    reward = 300_000_000_000_000  # 300T
    user["trial"] += reward
    user["last_weekly"] = now
    save_data()

    embed = create_casino_embed(
        "Weekly Jackpot Claimed!",
        f"🎰 Massive weekly bonus: **{format_sheckles(reward)} sheckles**!\n"
        f"💰 New Trial Balance: **{format_sheckles(user['trial'])} sheckles**",
        CASINO_THEME["success"],
        ctx.author
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
    await ctx.send(embed=embed)

# ==========================================
# 📊 HELP & INFORMATION COMMANDS
# ==========================================

@bot.command(aliases=['commands', 'cmds'])
async def guide(ctx):
    """📋 Display help information for bot commands"""
    embed = create_casino_embed(
        "Welcome to Casino Paradise!",
        "🎰 **Where fortunes are made and dreams come true!**",
        CASINO_THEME["primary"],
        ctx.author
    )

    embed.add_field(
        name="🎮 **Games** (Interactive Buttons!)",
        value="`!coinflip` `!blackjack` `!roulette` `!slot` `!dice`",
        inline=False
    )
    embed.add_field(
        name="💰 **Account Management**",
        value="`!balance` `!switch` `!claimdaily` `!claimweekly`",
        inline=False
    )
    embed.add_field(
        name="📊 **Statistics & Social**",
        value="`!stats` `!leaderboard` `!detailed_stats` `!global_stats`",
        inline=False
    )
    embed.add_field(
        name="🏆 **Achievements & Trading**",
        value="`!achievements` `!trade` `!shop` `!inventory`",
        inline=False
    )
    embed.add_field(
        name="⚔️ **PvP System**",
        value="`!pvp` `!spectate` `!pvpstats`",
        inline=False
    )

    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")
    embed.add_field(
        name="⚠️ **Casino Rules**",
        value="• Fair games for everyone\n• Good luck and have fun!\n• Play responsibly!",
        inline=False
    )

    await ctx.send(embed=embed)

# ==========================================
# 📊 STATISTICS COMMANDS  
# ==========================================

@bot.command()
async def stats(ctx):
    """📊 View your gambling statistics"""
    user = get_user(ctx.author.id)
    win_rate = (user["wins"] / user["bets"] * 100) if user["bets"] > 0 else 0
    current_win_rate = get_user_win_rate(ctx.author.id) * 100

    embed = create_casino_embed(
        f"{ctx.author.display_name}'s Statistics",
        "",
        CASINO_THEME["info"],
        ctx.author
    )

    embed.add_field(name="🎲 Total Bets", value=f"**{user['bets']:,}**", inline=True)
    embed.add_field(name="🏆 Wins", value=f"**{user['wins']:,}**", inline=True)
    embed.add_field(name="💀 Losses", value=f"**{user['losses']:,}**", inline=True)
    embed.add_field(name="📈 Win Rate", value=f"**{win_rate:.1f}%**", inline=True)
    embed.add_field(name="🎯 Current Odds", value=f"**{current_win_rate:.1f}%**", inline=True)
    embed.add_field(name="💰 Total Balance", value=f"**{format_sheckles(user['trial'] + user['premium'])}**", inline=True)

    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(aliases=['detailedstats'])
async def detailed_stats(ctx, member: discord.Member = None):
    """📊 View detailed gambling statistics"""
    target = member or ctx.author
    user = get_user(target.id)

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_stats WHERE user_id = ?', (str(target.id),))
        db_stats = cursor.fetchone()
        conn.close()
    except:
        db_stats = None

    win_rate = (user["wins"] / user["bets"] * 100) if user["bets"] > 0 else 0
    current_win_rate = get_user_win_rate(target.id) * 100

    embed = create_casino_embed(
        f"{target.display_name}'s Detailed Statistics",
        "",
        CASINO_THEME["info"],
        target
    )

    # Basic stats
    embed.add_field(name="🎲 Total Bets", value=f"**{user['bets']:,}**", inline=True)
    embed.add_field(name="🏆 Wins", value=f"**{user['wins']:,}**", inline=True)
    embed.add_field(name="💀 Losses", value=f"**{user['losses']:,}**", inline=True)
    embed.add_field(name="📈 Win Rate", value=f"**{win_rate:.1f}%**", inline=True)
    embed.add_field(name="🎯 Current Odds", value=f"**{current_win_rate:.1f}%**", inline=True)
    embed.add_field(name="💰 Total Balance", value=f"**{format_sheckles(user['trial'] + user['premium'])}**", inline=True)

    # Database stats if available
    if db_stats:
        total_profit = db_stats[1] if db_stats[1] else 0
        biggest_win = db_stats[2] if db_stats[2] else 0
        biggest_loss = db_stats[3] if db_stats[3] else 0

        embed.add_field(name="💸 Total Profit/Loss", value=f"**{format_sheckles(total_profit)}**", inline=True)
        embed.add_field(name="🎉 Biggest Win", value=f"**{format_sheckles(biggest_win)}**", inline=True)
        embed.add_field(name="💔 Biggest Loss", value=f"**{format_sheckles(biggest_loss)}**", inline=True)

    embed.set_thumbnail(url=target.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(aliases=['globalstats'])
async def global_stats(ctx):
    """🌍 View global casino statistics"""
    embed = create_casino_embed(
        "🌍 Global Casino Statistics",
        "",
        CASINO_THEME["premium"]
    )

    embed.add_field(name="🎲 Total Bets", value=f"**{casino_global_stats['total_bets']:,}**", inline=True)
    embed.add_field(name="💰 Total Wagered", value=f"**{format_sheckles(casino_global_stats['total_wagered'])}**", inline=True)
    embed.add_field(name="🏆 Total Won", value=f"**{format_sheckles(casino_global_stats['total_won'])}**", inline=True)
    embed.add_field(name="💸 Total Lost", value=f"**{format_sheckles(casino_global_stats['total_lost'])}**", inline=True)
    embed.add_field(name="👥 Total Players", value=f"**{len(balances):,}**", inline=True)
    embed.add_field(name="🎮 Active Games", value=f"**{len(active_pvp_games)}**", inline=True)

    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")
    await ctx.send(embed=embed)

@bot.command(aliases=['lb'])
async def leaderboard(ctx, mode: str = "trial"):
    """🏆 View the richest users"""
    mode = mode.lower()
    if mode not in ["trial", "premium"]:
        embed = create_casino_embed(
            "❌ Invalid Mode",
            "Use `trial` or `premium`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    sorted_balances = sorted(balances.items(), key=lambda item: item[1][mode], reverse=True)
    top_users = sorted_balances[:10]

    description = ""
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅", "🏅"]

    for i, (uid, data) in enumerate(top_users):
        try:
            member = await bot.fetch_user(int(uid))
            description += f"{medals[i]} **{member.name}** — {format_sheckles(data[mode])} sheckles\n"
        except:
            description += f"{medals[i]} **Unknown User** — {format_sheckles(data[mode])} sheckles\n"

    embed = create_casino_embed(
        f"{mode.capitalize()} Leaderboard",
        description,
        CASINO_THEME["primary"]
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")
    await ctx.send(embed=embed)

@bot.command()
async def achievements(ctx, member: discord.Member = None):
    """🏆 View your achievements and badges"""
    target = member or ctx.author
    user = get_user(target.id)

    embed = create_casino_embed(
        f"{target.display_name}'s Achievements",
        "",
        CASINO_THEME["premium"],
        target
    )

    # Basic achievement logic
    achievements_earned = []

    if user["wins"] >= 100:
        achievements_earned.append("🎯 **Century Club** - 100+ wins")
    if user["bets"] >= 500:
        achievements_earned.append("🎲 **High Roller** - 500+ bets")
    if user["trial"] + user["premium"] >= 1_000_000_000_000_000:  # 1Q
        achievements_earned.append("💰 **Billionaire** - 1Q+ total balance")
    if user["wins"] > 0 and (user["wins"] / user["bets"]) >= 0.6:
        achievements_earned.append("🍀 **Lucky Streak** - 60%+ win rate")

    # Display achievements
    if achievements_earned:
        embed.add_field(
            name="🏆 Earned Achievements",
            value="\n".join(achievements_earned),
            inline=False
        )
    else:
        embed.add_field(
            name="🏆 Achievements",
            value="No achievements earned yet. Keep playing!",
            inline=False
        )

    # Display badges
    if user["cosmetics"]["badges"]:
        badges_display = " ".join([f"🏅 {badge}" for badge in user["cosmetics"]["badges"]])
        embed.add_field(name="🎖️ Badges", value=badges_display, inline=False)
    else:
        embed.add_field(name="🎖️ Badges", value="No badges owned", inline=False)

    embed.set_thumbnail(url=target.display_avatar.url)
    await ctx.send(embed=embed)

# ==========================================
# 🛒 TRADING & SHOP SYSTEM
# ==========================================

@bot.command()
async def trade(ctx, member: discord.Member = None, amount: str = None):
    """💱 Trade sheckles with another player"""
    if not member or not amount:
        embed = create_casino_embed(
            "❌ Invalid Usage",
            "**Usage:** `!trade @player <amount>`\n"
            "**Example:** `!trade @friend 10T`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if member.id == ctx.author.id:
        embed = create_casino_embed(
            "❌ Invalid Target",
            "You can't trade with yourself!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if member.bot:
        embed = create_casino_embed(
            "❌ Invalid Target",
            "You can't trade with bots!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    try:
        trade_amount = parse_sheckles(amount)
    except:
        embed = create_casino_embed(
            "❌ Invalid Amount",
            "Use valid amount like `10T`, `5B`, etc.",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if trade_amount <= 0:
        embed = create_casino_embed(
            "❌ Invalid Amount",
            "Trade amount must be positive!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    trader = get_user(ctx.author.id)
    if trader[trader["mode"]] < trade_amount:
        embed = create_casino_embed(
            "❌ Insufficient Funds",
            f"You need **{format_sheckles(trade_amount)}** sheckles to make this trade!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    # Execute trade
    recipient = get_user(member.id)
    trader[trader["mode"]] -= trade_amount
    recipient[recipient["mode"]] += trade_amount
    save_data()

    embed = create_casino_embed(
        "✅ Trade Completed!",
        f"**{ctx.author.display_name}** sent **{format_sheckles(trade_amount)} sheckles** to **{member.display_name}**!\n\n"
        f"💰 **{ctx.author.display_name}'s new balance:** {format_sheckles(trader[trader['mode']])}\n"
        f"💰 **{member.display_name}'s new balance:** {format_sheckles(recipient[recipient['mode']])}",
        CASINO_THEME["success"]
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
    await ctx.send(embed=embed)

@bot.command()
async def shop(ctx):
    """🛒 Browse the casino shop for cosmetics and boosters"""
    embed = create_casino_embed(
        "🛒 Casino Shop",
        "Welcome to the Casino Paradise Shop!",
        CASINO_THEME["premium"]
    )

    embed.add_field(
        name="🎨 **Cosmetics**",
        value="🏅 **VIP Badge** - 100T sheckles\n"
              "🌟 **Lucky Badge** - 50T sheckles\n"
              "💎 **Diamond Theme** - 200T sheckles",
        inline=False
    )

    embed.add_field(
        name="⚡ **Boosters** (Coming Soon)",
        value="🍀 **Luck Booster** - Increases win rate for 24h\n"
              "💰 **Double Rewards** - 2x daily/weekly rewards\n"
              "🎯 **Streak Protection** - Prevents loss streaks",
        inline=False
    )

    embed.add_field(
        name="💡 **How to Purchase**",
        value="Use `!buy <item>` to purchase items\n"
              "Example: `!buy vip_badge`",
        inline=False
    )

    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")
    await ctx.send(embed=embed)

@bot.command()
async def inventory(ctx, member: discord.Member = None):
    """🎒 View your inventory of cosmetics and items"""
    target = member or ctx.author
    user = get_user(target.id)

    embed = create_casino_embed(
        f"{target.display_name}'s Inventory",
        "",
        CASINO_THEME["info"],
        target
    )

    # Current theme
    embed.add_field(
        name="🎨 Active Theme",
        value=f"**{user['cosmetics']['theme'].title()}**",
        inline=True
    )

    # Badges
    if user["cosmetics"]["badges"]:
        badges_display = "\n".join([f"🏅 {badge.replace('_', ' ').title()}" for badge in user["cosmetics"]["badges"]])
        embed.add_field(name="🎖️ Owned Badges", value=badges_display, inline=False)
    else:
        embed.add_field(name="🎖️ Badges", value="No badges owned", inline=False)

    # Boosters
    if user["boosters"]:
        boosters_display = "\n".join([f"⚡ {booster.replace('_', ' ').title()}" for booster in user["boosters"]])
        embed.add_field(name="⚡ Active Boosters", value=boosters_display, inline=False)
    else:
        embed.add_field(name="⚡ Boosters", value="No active boosters", inline=False)

    embed.set_thumbnail(url=target.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
async def buy(ctx, item: str = None):
    """💳 Purchase items from the casino shop"""
    if not item:
        embed = create_casino_embed(
            "❌ Missing Item",
            "**Usage:** `!buy <item>`\n"
            "Use `!shop` to see available items",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    user = get_user(ctx.author.id)
    item = item.lower()

    # Shop items with prices
    shop_items = {
        "vip_badge": {"price": 100_000_000_000_000, "type": "badge", "name": "VIP Badge"},
        "lucky_badge": {"price": 50_000_000_000_000, "type": "badge", "name": "Lucky Badge"},
        "diamond_theme": {"price": 200_000_000_000_000, "type": "theme", "name": "Diamond Theme"}
    }

    if item not in shop_items:
        embed = create_casino_embed(
            "❌ Item Not Found",
            "Use `!shop` to see available items",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    item_data = shop_items[item]
    price = item_data["price"]

    if user[user["mode"]] < price:
        embed = create_casino_embed(
            "❌ Insufficient Funds",
            f"You need **{format_sheckles(price)}** sheckles to buy **{item_data['name']}**!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    # Check if already owned
    if item_data["type"] == "badge" and item in user["cosmetics"]["badges"]:
        embed = create_casino_embed(
            "❌ Already Owned",
            "You already own this badge!",
            CASINO_THEME["warning"]
        )
        return await ctx.send(embed=embed)
    elif item_data["type"] == "theme" and user["cosmetics"]["theme"] == item:
        embed = create_casino_embed(
            "❌ Already Owned",
            "You already own this theme!",
            CASINO_THEME["warning"]
        )
        return await ctx.send(embed=embed)

    # Purchase item
    user[user["mode"]] -= price

    if item_data["type"] == "badge":
        user["cosmetics"]["badges"].append(item)
    elif item_data["type"] == "theme":
        user["cosmetics"]["theme"] = item

    save_data()

    embed = create_casino_embed(
        "✅ Purchase Successful!",
        f"You bought **{item_data['name']}** for **{format_sheckles(price)} sheckles**!\n"
        f"💰 **New Balance:** {format_sheckles(user[user['mode']])} sheckles",
        CASINO_THEME["success"],
        ctx.author
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7abKhOpu0NwenH3O/gif")
    await ctx.send(embed=embed)

# ==========================================
# ⚔️ PVP SYSTEM COMMANDS
# ==========================================

@bot.command(aliases=['challenge', 'duel'])
@commands.cooldown(1, 10, commands.BucketType.user)
async def pvp(ctx, opponent: discord.Member = None, game_type: str = None, amount: str = None):
    """⚔️ Challenge another player to a PvP game!"""
    if not opponent or not game_type or not amount:
        embed = create_casino_embed(
            "❌ Invalid Usage",
            "**Usage:** `!pvp @player <game> <amount>`\n"
            "**Games:** `coinflip`, `dice`\n"
            "**Example:** `!pvp @friend coinflip 10T`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if opponent.id == ctx.author.id:
        embed = create_casino_embed(
            "❌ Invalid Target",
            "You can't challenge yourself!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if opponent.bot:
        embed = create_casino_embed(
            "❌ Invalid Target", 
            "You can't challenge bots!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    game_type = game_type.lower()
    if game_type not in ["coinflip", "dice"]:
        embed = create_casino_embed(
            "❌ Invalid Game",
            "Available PvP games: `coinflip`, `dice`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    # Check if challenger already has an active challenge
    if ctx.author.id in active_challenges:
        embed = create_casino_embed(
            "❌ Challenge Pending",
            "You already have an active challenge! Wait for it to expire or be answered.",
            CASINO_THEME["warning"]
        )
        return await ctx.send(embed=embed)

    try:
        if amount.lower() == "all":
            challenger = get_user(ctx.author.id)
            bet_amount = challenger[challenger["mode"]]
        else:
            bet_amount = parse_sheckles(amount)
    except:
        embed = create_casino_embed(
            "❌ Invalid Amount",
            "Use valid amount like `10T`, `5B`, etc. or `all`",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    if bet_amount <= 0:
        embed = create_casino_embed(
            "❌ Invalid Bet",
            "Bet amount must be positive!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    challenger = get_user(ctx.author.id)
    if challenger[challenger["mode"]] < bet_amount:
        embed = create_casino_embed(
            "❌ Insufficient Funds",
            f"You need **{format_sheckles(bet_amount)}** sheckles to make this challenge!",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    # Create challenge
    challenger_name = format_user_name_for_pvp(ctx.author)
    opponent_name = format_user_name_for_pvp(opponent)
    
    embed = create_casino_embed(
        "⚔️ PvP Challenge!",
        f"**{challenger_name}** challenges **{opponent_name}**!\n\n"
        f"🎮 **Game:** {game_type.title()}\n"
        f"💰 **Stakes:** {format_sheckles(bet_amount)} sheckles each\n"
        f"🏆 **Winner gets:** {format_sheckles(bet_amount * 2)} sheckles\n\n"
        f"**{opponent_name}**, do you accept this challenge?",
        CASINO_THEME["premium"],
        ctx.author,
        is_pvp=True
    )
    embed.set_thumbnail(url="https://media.giphy.com/media/3o7TKwmnDgQb5jSP8O/gif")

    view = PvPChallengeView(ctx.author.id, opponent.id, game_type, bet_amount)
    message = await ctx.send(f"{opponent.mention}", embed=embed, view=view)
    view.message = message

    # Store active challenge
    active_challenges[ctx.author.id] = {
        "opponent_id": opponent.id,
        "game_type": game_type,
        "bet_amount": bet_amount,
        "message_id": message.id
    }

@bot.command()
async def spectate(ctx, game_id: str = None):
    """👀 Spectate an active PvP game"""
    if not active_pvp_games:
        embed = create_casino_embed(
            "❌ No Active Games",
            "There are no PvP games happening right now!",
            CASINO_THEME["info"]
        )
        return await ctx.send(embed=embed)

    if not game_id:
        # List all active games
        games_list = ""
        for gid, game_data in active_pvp_games.items():
            player_names = []
            for pid in game_data["players"]:
                try:
                    user = await bot.fetch_user(pid)
                    player_names.append(format_user_name_for_pvp(user, pid))
                except:
                    player_names.append("Unknown")

            games_list += f"**{gid[:8]}...** - {game_data['game_type']} ({' vs '.join(player_names)})\n"

        embed = create_casino_embed(
            "👀 Active PvP Games",
            f"Use `!spectate <game_id>` to watch a specific game:\n\n{games_list}",
            CASINO_THEME["info"]
        )
        return await ctx.send(embed=embed)

    # Add to spectators
    if game_id in active_pvp_games:
        if ctx.author.id not in active_pvp_games[game_id]["spectators"]:
            active_pvp_games[game_id]["spectators"].append(ctx.author.id)

        embed = create_casino_embed(
            "👀 Now Spectating",
            f"You're now watching the game! 🍿",
            CASINO_THEME["info"],
            ctx.author
        )
        await ctx.send(embed=embed)
    else:
        embed = create_casino_embed(
            "❌ Game Not Found",
            "That game doesn't exist or has ended!",
            CASINO_THEME["danger"]
        )
        await ctx.send(embed=embed)

@bot.command()
async def pvpstats(ctx, member: discord.Member = None):
    """📊 View PvP statistics"""
    target = member or ctx.author
    user = get_user(target.id)

    # Calculate PvP-specific stats (you can expand this with dedicated PvP tracking)
    embed = create_casino_embed(
        f"{target.display_name}'s PvP Stats",
        f"🎮 **Total Games:** {user['bets']}\n"
        f"🏆 **Wins:** {user['wins']}\n"
        f"💀 **Losses:** {user['losses']}\n"
        f"📈 **Win Rate:** {(user['wins'] / user['bets'] * 100) if user['bets'] > 0 else 0:.1f}%",
        CASINO_THEME["info"],
        target
    )
    await ctx.send(embed=embed)

# ==========================================
# 👑ADMIN COMMANDS
# ==========================================

@bot.command()
async def addbalance(ctx, member: discord.Member, mode: str, amount: str):
    """[ADMIN] Add balance to a user"""
    if ctx.author.id != OWNER_ID:
        embed = create_casino_embed(
            "❌ Access Denied",
            "Only the casino owner can use this command",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    user = get_user(member.id)
    try:
        amt = parse_sheckles(amount)
        mode = mode.lower()
        if mode not in ["trial", "premium"]:
            raise Exception()
    except:
        embed = create_casino_embed(
            "❌ Invalid Input",
            "Use valid mode (`trial` or `premium`) and amount (e.g. `10T`)",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    balance_before = user[mode]
    user[mode] += amt
    save_data()
    
    # Log admin action
    log_user_action(member.id, "ADMIN_BALANCE_ADD", f"Admin {ctx.author.id} added {format_sheckles(amt)} to {mode} balance")
    logger.info(f"👑 ADMIN ACTION: {ctx.author.id} added {format_sheckles(amt)} to user {member.id} ({mode} balance)")

    embed = create_casino_embed(
        "✅ Balance Updated",
        f"Added **{format_sheckles(amt)}** to **{member.display_name}**'s `{mode}` balance\n"
        f"**Before:** {format_sheckles(balance_before)}\n"
        f"**After:** {format_sheckles(user[mode])}",
        CASINO_THEME["success"]
    )
    await ctx.send(embed=embed)

@bot.command()
async def systemstatus(ctx):
    """[ADMIN] View system status and backup information"""
    if ctx.author.id != OWNER_ID:
        embed = create_casino_embed(
            "❌ Access Denied",
            "Only the casino owner can use this command",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    try:
        import psutil
        
        # System info
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('.')
        
        # File sizes
        data_size = os.path.getsize(DATA_FILE) if os.path.exists(DATA_FILE) else 0
        db_size = os.path.getsize(DB_FILE) if os.path.exists(DB_FILE) else 0
        
        # Backup info
        backup_count = 0
        if os.path.exists(BACKUP_DIR):
            backup_count = len([f for f in os.listdir(BACKUP_DIR) if f.endswith(('.json', '.db'))])
        
        # Latest backup
        latest_backup = "None"
        if os.path.exists(BACKUP_DIR):
            backup_files = []
            for file in os.listdir(BACKUP_DIR):
                if file.startswith('balances_'):
                    file_path = os.path.join(BACKUP_DIR, file)
                    backup_files.append((file, os.path.getctime(file_path)))
            if backup_files:
                latest_backup = max(backup_files, key=lambda x: x[1])[0]
        
        embed = create_casino_embed(
            "🖥️ System Status",
            "",
            CASINO_THEME["info"]
        )
        
        embed.add_field(
            name="💾 Data Files",
            value=f"**JSON:** {data_size / 1024:.1f} KB\n"
                  f"**Database:** {db_size / 1024:.1f} KB\n"
                  f"**Users:** {len(balances):,}",
            inline=True
        )
        
        embed.add_field(
            name="📦 Backups",
            value=f"**Count:** {backup_count}\n"
                  f"**Latest:** {latest_backup[:20]}...\n"
                  f"**Auto-backup:** {'✅ Running' if auto_backup.is_running() else '❌ Stopped'}",
            inline=True
        )
        
        embed.add_field(
            name="🖥️ System",
            value=f"**Memory:** {memory.percent:.1f}% used\n"
                  f"**Disk:** {disk.percent:.1f}% used\n"
                  f"**Auto-save:** {'✅ Running' if auto_save.is_running() else '❌ Stopped'}",
            inline=True
        )
        
        embed.add_field(
            name="🎮 Casino Stats",
            value=f"**Total Bets:** {casino_global_stats['total_bets']:,}\n"
                  f"**Active PvP:** {len(active_pvp_games)}\n"
                  f"**Active Challenges:** {len(active_challenges)}",
            inline=True
        )
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Error in systemstatus command: {e}")
        embed = create_casino_embed(
            "❌ Error",
            f"Failed to get system status: {str(e)}",
            CASINO_THEME["danger"]
        )
        await ctx.send(embed=embed)

@bot.command()
async def backup(ctx):
    """[ADMIN] Create manual backup"""
    if ctx.author.id != OWNER_ID:
        embed = create_casino_embed(
            "❌ Access Denied",
            "Only the casino owner can use this command",
            CASINO_THEME["danger"]
        )
        return await ctx.send(embed=embed)

    try:
        create_backup()
        embed = create_casino_embed(
            "✅ Backup Created",
            "Manual backup completed successfully!",
            CASINO_THEME["success"]
        )
        logger.info(f"👑 ADMIN ACTION: {ctx.author.id} created manual backup")
    except Exception as e:
        embed = create_casino_embed(
            "❌ Backup Failed",
            f"Error creating backup: {str(e)}",
            CASINO_THEME["danger"]
        )
        logger.error(f"❌ Manual backup failed: {e}")
    
    await ctx.send(embed=embed)

# ==========================================
# 🚀 START THE BOT
# ==========================================

@bot.event
async def on_ready():
    logger.info(f"🎰 {bot.user} is now running Casino Paradise!")
    logger.info(f"🏛️ Connected to {len(bot.guilds)} servers")
    logger.info(f"👤 Loaded {len(balances)} user accounts")
    logger.info(f"🎲 Games ready to play!")
    logger.info(f"💰 Casino is open for business!")

    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing, 
                name="🎰 Casino Paradise | !guide"
            )
        )
        logger.info("✅ Bot presence set successfully")
    except Exception as e:
        logger.error(f"❌ Error setting bot presence: {e}")
    
    # Start backup tasks
    try:
        auto_backup.start()
        auto_save.start()
        logger.info("✅ Automatic backup and save tasks started")
    except Exception as e:
        logger.error(f"❌ Error starting backup tasks: {e}")
    
    # Create initial backup
    try:
        create_backup()
        logger.info("📦 Initial backup created on startup")
    except Exception as e:
        logger.error(f"❌ Error creating initial backup: {e}")

@bot.event
async def on_message(message):
    """Process messages and prevent duplicate responses"""
    # Ignore messages from bots (including this bot)
    if message.author == bot.user:
        return
    if message.author.bot:
        return

    # Process commands
    await bot.process_commands(message)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors gracefully"""
    if isinstance(error, commands.CommandOnCooldown):
        embed = create_casino_embed(
            "⏳ Cooldown Active",
            f"Try again in {error.retry_after:.2f} seconds!",
            CASINO_THEME["warning"]
        )
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = create_casino_embed(
            "❌ Missing Arguments",
            f"Please check `!guide` for proper command usage.",
            CASINO_THEME["danger"]
        )
        await ctx.send(embed=embed)
    else:
        logger.error(f"❌ Command error: {error}")
        logger.error(f"Command: {ctx.command}, User: {ctx.author.id}, Guild: {ctx.guild.id if ctx.guild else 'DM'}")
        logger.error(traceback.format_exc())
        
        embed = create_casino_embed(
            "❌ Something went wrong!",
            "Please try again or contact support.",
            CASINO_THEME["danger"]
        )
        await ctx.send(embed=embed)

async def graceful_shutdown():
    """Perform graceful shutdown with data saving"""
    try:
        logger.info("🛑 Graceful shutdown initiated...")
        
        # Stop backup tasks
        if auto_backup.is_running():
            auto_backup.stop()
        if auto_save.is_running():
            auto_save.stop()
        
        # Save all data
        save_data()
        logger.info("💾 Final data save completed")
        
        # Create final backup
        create_backup()
        logger.info("📦 Final backup created")
        
        logger.info("✅ Graceful shutdown completed")
        
    except Exception as e:
        logger.error(f"❌ Error during graceful shutdown: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    if not TOKEN:
        logger.critical("❌ Error: DISCORD_TOKEN environment variable not set!")
        logger.critical("🔑 Please add your bot token to the Secrets tab")
        exit(1)

    try:
        logger.info("🚀 Starting Casino Paradise Bot...")
        
        # Log startup information
        logger.info(f"📂 Data file: {DATA_FILE}")
        logger.info(f"🗄️ Database file: {DB_FILE}")
        logger.info(f"📦 Backup directory: {BACKUP_DIR}")
        
        bot.run(TOKEN)
        
    except discord.LoginFailure:
        logger.critical("❌ Error: Invalid Discord token!")
        logger.critical("🔑 Please check your DISCORD_TOKEN in the Secrets tab")
    except discord.HTTPException as e:
        logger.critical(f"❌ HTTP Error: {e}")
        logger.critical(traceback.format_exc())
    except KeyboardInterrupt:
        logger.info("🛑 Bot shutdown requested")
        # Run graceful shutdown in asyncio loop
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(graceful_shutdown())
            loop.close()
        except Exception as shutdown_error:
            logger.error(f"❌ Error during graceful shutdown: {shutdown_error}")
    except Exception as e:
        logger.critical(f"❌ Failed to start bot: {e}")
        logger.critical(traceback.format_exc())
        logger.critical("🔧 Check your internet connection and token")
        
        # Try to save data before crashing
        try:
            save_data()
            create_backup()
            logger.info("💾 Emergency data save completed")
        except Exception as save_error:
            logger.critical(f"❌ Emergency save failed: {save_error}")
    
    finally:
        logger.info("🏁 Bot execution finished")