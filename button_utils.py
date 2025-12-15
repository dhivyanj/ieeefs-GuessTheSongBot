import random

import discord


def getRandomButtonStyle() -> discord.ButtonStyle:
    """Return a random ButtonStyle from a small set for visual variety."""
    choices = [discord.ButtonStyle.blurple, discord.ButtonStyle.green, discord.ButtonStyle.red]
    return random.choice(choices)
