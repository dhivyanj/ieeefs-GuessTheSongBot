import random

import discord


def get_random_button_style() -> discord.ButtonStyle:
    choices = [discord.ButtonStyle.blurple, discord.ButtonStyle.green, discord.ButtonStyle.red]
    return random.choice(choices)
