# bot.py
import os
import asyncio
from discord.ext import commands
from discord.ext.commands.core import before_invoke
import youtube_dl
import discord
import random
import itertools
import math
# from dotenv import load_dotenv
import googleapiclient.discovery

# Silence useless bug reports messages
youtube_dl.utils.bug_reports_message = lambda: ''

# load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
api_key=os.getenv('YOUTUBE_API')
api_service_name = "youtube"
api_version = "v3"
youtube = googleapiclient.discovery.build(api_service_name, api_version, developerKey=api_key)

ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}
bot= commands.Bot(command_prefix='!')

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')


class Song:
    def __init__(self,search:str):
        request=youtube.search().list(q=search,part="snippet",type='video',order="relevance",maxResults=1)
        responce=request.execute()
        # print(responce)
        for i in responce['items']:
            print(i['snippet']['title'])
        self.url="https://youtu.be/"+responce['items'][0]['id']['videoId']
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            self.info = ydl.extract_info(self.url, download=False)
            URL = self.info['formats'][0]['url']
            self.title = self.info['title']
            self.songEmbed=discord.Embed(title="Queued:",description='\n\n[**{}**]({})'.format(self.title,self.url),color=0x330aff)
            self.source=discord.FFmpegPCMAudio(URL, **FFMPEG_OPTIONS)

class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]

class VC:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.voice=None
        self._loop = False
        self.current = None
        self.songs = SongQueue()
        self.play_next_song = asyncio.Event()
        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.play_next_song.clear()
            self.current = await self.songs.get()
            print(self.current.source)
            self.voice.play(self.current.source, after=self.toggle_next)
            await self.play_next_song.wait()

    def toggle_next(self,error=None):
        self.play_next_song.set()

    def skip(self):
        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None

    
class final_Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VC(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('An error occurred: {}'.format(str(error)))

    @commands.command(name='log')
    async def logPlaying(self,ctx: commands.Context):
        if ctx.voice_state.is_playing:
            print("Playing")

    @commands.command(name='join')
    async def _join(self, ctx: commands.Context):
        destination=discord.utils.get(ctx.guild.voice_channels,id=ctx.author.voice.channel.id)
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return
        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'])
    async def _leave(self, ctx: commands.Context):
        if not ctx.voice_state.voice:
            return await ctx.send('Not connected to any voice channel.')
        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='skip')
    async def _skip(self, ctx: commands.Context):
        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')
        else:
            ctx.voice_state.skip()

    @commands.command(name='stop')
    async def _stop(self, ctx: commands.Context):
        ctx.voice_state.songs.clear()
        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()

    @commands.command(name='pause')
    #@commands.has_permissions(manage_guild=True)
    async def _pause(self, ctx: commands.Context):
        if ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
        else:
            return await ctx.send('Not playing any music right now...')

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')
        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop

    @commands.command(name='resume')
    #@commands.has_permissions(manage_guild=True)
    async def _resume(self, ctx: commands.Context):
        if ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.title}**]({1.url})\n'.format(i + 1, song)

        embed = (discord.Embed(description='**{} tracks:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='Viewing page {}/{}'.format(page, pages)))
        await ctx.send(embed=embed)

    @commands.command(name='play')
    async def play(self,ctx: commands.Context,*args):
        search=" ".join(args)
        if(ctx.author.voice!=None):
            if not ctx.voice_state.voice:
                await ctx.invoke(self._join)
            song=Song(search)
            ctx.voice_state.voice=discord.utils.get(bot.voice_clients, guild=ctx.guild)
            print(ctx.voice_state.voice)
            await ctx.voice_state.songs.put(song)
            await ctx.send(embed=song.songEmbed)
        else:
            await ctx.send("You must be connected to a voice channel.")

bot.add_cog(final_Music(bot))
bot.run(TOKEN)