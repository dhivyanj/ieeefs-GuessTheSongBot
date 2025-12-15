import random

import discord


def getRandomButtonStyle() -> discord.ButtonStyle:
    choices = [discord.ButtonStyle.blurple, discord.ButtonStyle.green, discord.ButtonStyle.red]
    return random.choice(choices)
