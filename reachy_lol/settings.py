from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class EventPreference(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled: bool=True
    reaction: Literal['Hype','Supportive','Very excited','Happy','Silent','Celebrate']='Happy'

def event_defaults():
    return {k:EventPreference(reaction=v) for k,v in {
        'kill':'Hype','death':'Supportive','multikill':'Very excited',
        'objective':'Happy','lowhp':'Silent','victory':'Celebrate'}.items()}

class Preferences(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(default='默默',min_length=1,max_length=18)
    voice: Literal['velvet','sparkle','cedar','breeze'] | None=None
    intensity: Literal['chill','normal','chaos']='normal'
    volume: float=Field(default=.35,ge=0,le=1,allow_inf_nan=False)
    input_device: str | None=Field(default=None,max_length=300)
    output_device: str | None=Field(default=None,max_length=300)
    seat_yaw: float | None=Field(default=None,ge=-20,le=20,allow_inf_nan=False)
    events: dict[Literal['kill','death','multikill','objective','lowhp','victory'],EventPreference]=Field(default_factory=event_defaults)

    def normalized_events(self):
        return {**event_defaults(),**self.events}

VOICE_ENV={'velvet':'VOICE_VELVET','sparkle':'VOICE_SPARKLE','cedar':'VOICE_CEDAR','breeze':'VOICE_BREEZE'}
VOICE_ROLE={'velvet':'aqi','sparkle':'anao','cedar':'aqi','breeze':'anao'}
EVENT_TYPES={'ChampionKill':'kill','Multikill':'multikill','DragonKill':'objective',
             'BaronKill':'objective','HeraldKill':'objective','GameEnd':'victory'}
