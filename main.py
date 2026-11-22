import os, json, random, asyncio, subprocess, requests, textwrap
from pathlib import Path
import edge_tts
from PIL import Image, ImageDraw, ImageFont

OUT = Path('output'); OUT.mkdir(exist_ok=True)
TOPICS = [
 {'name':'Zorluklar karşısında umut', 'hook':'Zor günlerden mi geçiyorsun?', 'verse':'Şüphesiz güçlükle beraber bir kolaylık vardır. (İnşirâh 94:6)', 'hadith':'Müminin işi ne hoştur! Her hâli onun için hayırlıdır. (Müslim, Zühd 64, hadis 2999; anlamından kısa aktarım)', 'advice':'Bugün küçük de olsa hayırlı bir adım at. Allah’tan yardım iste.'},
 {'name':'Güzel söz', 'hook':'Bir söz, bütün gününü değiştirebilir.', 'verse':'Kullarıma söyle: Sözün en güzelini söylesinler. (İsrâ 17:53; anlamından kısa aktarım)', 'hadith':'Allah’a ve ahiret gününe iman eden ya hayır söylesin ya sussun. (Buhârî 6018; Müslim 47)', 'advice':'Bugün birine güzel bir söz söyle. Kırıcı olmaktan kaçın.'},
 {'name':'Öfke kontrolü', 'hook':'Sinirlendiğinde gerçek güç nedir?', 'verse':'Onlar öfkelerini yenerler ve insanları affederler. (Âl-i İmrân 3:134; anlamından kısa aktarım)', 'hadith':'Güçlü kişi, öfke anında kendine hâkim olandır. (Buhârî 6114; Müslim 2609; anlamından kısa aktarım)', 'advice':'Öfkelendiğinde aceleyle cevap verme. Sabır ve güzel ahlakı seç.'}
]

def choose_topic():
    key = os.getenv('GEMINI_API_KEY')
    if not key: return random.choice(TOPICS)
    try:
        names = [x['name'] for x in TOPICS]
        prompt = 'Gençler için bugün en faydalı İslami hatırlatma konusunu şu listeden seç. Yalnızca listedeki ismi yaz: ' + ', '.join(names)
        url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'
        r = requests.post(url, headers={'x-goog-api-key':key}, json={'contents':[{'parts':[{'text':prompt}]}]}, timeout=30)
        r.raise_for_status()
        answer = r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        return next((x for x in TOPICS if x['name'] in answer), random.choice(TOPICS))
    except Exception as e:
        print('Gemini kullanılamadı, hazır konu seçiliyor:', e)
        return random.choice(TOPICS)

def download_background():
    key = os.environ['PIXABAY_API_KEY']
    for term in ('mountains nature', 'ocean landscape', 'forest aerial'):
        r = requests.get('https://pixabay.com/api/videos/', params={'key':key,'q':term,'per_page':20,'safesearch':'true'}, timeout=30)
        r.raise_for_status()
        hits = r.json().get('hits', [])
        random.shuffle(hits)
        for hit in hits:
            videos = hit.get('videos', {})
            choice = videos.get('medium') or videos.get('small') or videos.get('large') or {}
            url = choice.get('url')
            if url:
                data = requests.get(url, timeout=120)
                data.raise_for_status()
                (OUT/'nature.mp4').write_bytes(data.content)
                return hit.get('pageURL','')
    raise RuntimeError('Pixabay video bulamadı. API kotasını ve anahtarını kontrol et.')

def make_cards(topic):
    font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font = ImageFont.truetype(font_path, 58)
    small = ImageFont.truetype(font_path, 33)
    texts = [topic['hook'],topic['verse'],topic['hadith'],topic['advice']+'\nFaydalı bulduysan paylaş.']
    for i, value in enumerate(texts):
        im = Image.new('RGBA',(1080,1920),(0,0,0,0)); d = ImageDraw.Draw(im)
        lines=[]
        for paragraph in value.split('\n'):
            lines += textwrap.wrap(paragraph, width=27) or ['']
        line_height=90
        y=(1920-len(lines)*line_height)//2
        d.rounded_rectangle((55,y-75,1025,y+len(lines)*line_height+65),radius=30,fill=(0,0,0,185))
        for j,line in enumerate(lines):
            f = small if '(' in line and ')' in line else font
            d.text((540,y+j*line_height),line,font=f,anchor='mt',fill='white',stroke_width=1,stroke_fill='black')
        im.save(OUT/f'card{i}.png')
    return texts

async def make_audio(texts):
    durations=[]
    for i, value in enumerate(texts):
        await edge_tts.Communicate(value,voice='tr-TR-AhmetNeural',rate='-8%').save(str(OUT/f'voice{i}.mp3'))
        raw=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(OUT/f'voice{i}.mp3')],text=True)
        durations.append(float(raw.strip())+0.7)
    return durations

def make_video(durations):
    # One downloaded background, cropped vertically; narration and text change by segment.
    for i,duration in enumerate(durations):
        subprocess.run(['ffmpeg','-y','-stream_loop','-1','-i',str(OUT/'nature.mp4'),'-loop','1','-i',str(OUT/f'card{i}.png'),'-i',str(OUT/f'voice{i}.mp3'),'-filter_complex',
          '[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg];[bg][1:v]overlay=0:0:shortest=0[v]',
          '-map','[v]','-map','2:a','-t',str(duration),'-r','25','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','aac','-ar','44100','-shortest',str(OUT/f'part{i}.mp4')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    (OUT/'concat.txt').write_text(''.join(f"file 'part{i}.mp4'\n" for i in range(len(durations))))
    subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(OUT/'concat.txt'),'-c','copy',str(OUT/'short.mp4')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

async def main():
    topic=choose_topic()
    print('Seçilen konu:',topic['name'])
    source=download_background()
    texts=make_cards(topic)
    durations=await make_audio(texts)
    make_video(durations)
    (OUT/'sources.json').write_text(json.dumps({'topic':topic,'background':source},ensure_ascii=False,indent=2))
    print('Hazır: output/short.mp4')

if __name__=='__main__':
    asyncio.run(main())
