import os, json, random, asyncio, subprocess, textwrap, time
from pathlib import Path
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont

OUT = Path('output'); OUT.mkdir(exist_ok=True)

def topic():
    key = os.environ['GEMINI_API_KEY']
    base = 'https://generativelanguage.googleapis.com/v1beta'
    session = requests.Session()
    headers = {'x-goog-api-key': key}
    listing = session.get(f'{base}/models', headers=headers, timeout=30)
    if not listing.ok:
        raise RuntimeError(f'Gemini model listesi alınamadı ({listing.status_code}): {listing.text[:350]}')
    models = [m['name'] for m in listing.json().get('models', [])
              if 'generateContent' in m.get('supportedGenerationMethods', [])
              and 'gemini' in m.get('name', '').lower()]
    models.sort(key=lambda m: (not any(x in m for x in ('flash', 'lite')), 'preview' in m, m))
    if not models:
        raise RuntimeError('API anahtarına açık generateContent modeli bulunamadı.')
    prompt = ("Türkçe İslami kısa video için gençlerin gündelik hayatına uygun yaratıcı bir konu seç. "
              "Bir ayet ve sahih hadis için sure/ayet, eser/hadis numarası belirt. "
              "Emin olmadığın metni uydurma. Kısa anlam aktarımı kullan. "
              "Sadece name, hook, verse, hadith, advice anahtarları olan JSON döndür.")
    payload = {'contents': [{'parts': [{'text': prompt}]}],
               'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.9}}
    for model in models:
        r = session.post(f'{base}/{model}:generateContent', headers=headers,
                         json=payload, timeout=90)
        if r.status_code in (404, 400):
            print('Model kullanılamadı:', model, r.status_code)
            continue
        if not r.ok:
            raise RuntimeError(f'Gemini {r.status_code}: {r.text[:500]}')
        raw = r.json()['candidates'][0]['content']['parts'][0]['text']
        data = json.loads(raw)
        if not all(isinstance(data.get(k), str) and data[k].strip()
                   for k in ('name', 'hook', 'verse', 'hadith', 'advice')):
            raise ValueError('Gemini eksik içerik üretti.')
        print('Gemini modeli:', model)
        return data
    raise RuntimeError('Listelenen modellerin hiçbiri içerik üretemedi.')

def fallback_background():
    # No external stock footage: animated, abstract sky/landscape gradients.
    # drawbox + moving gradients generated from FFmpeg sources.
    subprocess.run([
        'ffmpeg', '-y', '-f', 'lavfi',
        '-i', 'color=c=0x173c55:s=540x960:r=25:d=80',
        '-vf', "drawbox=x=0:y=550:w=iw:h=410:color=0x123a34:t=fill,"
               "drawbox=x=0:y=720:w=iw:h=240:color=0x09251f:t=fill,"
               "drawbox=x='150+75*sin(t/5)':y='180+25*cos(t/6)':w=110:h=110:color=0xf4c980@0.35:t=fill,"
               "scale=1080:1920,format=yuv420p",
        '-t', '80', '-c:v', 'libx264', '-preset', 'ultrafast',
        str(OUT / 'nature.mp4')
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def pixabay_background():
    key=os.environ['PIXABAY_API_KEY']; session=requests.Session()
    for term in random.sample(['mountains','ocean','forest','waterfall','clouds','landscape'],6):
        r=session.get('https://pixabay.com/api/videos/',params={'key':key,'q':term,'per_page':20,'safesearch':'true'},timeout=30)
        if r.status_code==429:
            print('Pixabay API 429; bekleniyor'); time.sleep(10); continue
        r.raise_for_status(); hits=r.json().get('hits',[]); random.shuffle(hits)
        for hit in hits[:6]:
            for quality in ('small','medium'):
                url=hit.get('videos',{}).get(quality,{}).get('url')
                if not url: continue
                try:
                    with session.get(url,stream=True,timeout=60) as video:
                        if video.status_code==429: print('CDN 429, başka video deneniyor'); break
                        video.raise_for_status()
                        path=OUT/'nature.mp4'
                        with path.open('wb') as f:
                            for chunk in video.iter_content(1024*1024):
                                if chunk: f.write(chunk)
                    if path.stat().st_size>10000: return hit.get('pageURL','')
                except (requests.RequestException,OSError) as e: print('Video indirilemedi:',e)
    print('Pixabay erişilemedi; yedek hareketli arka plan hazırlanıyor.')
    fallback_background()
    return 'Generated abstract nature-inspired background (no external footage)' 

def background():
    try:
        return pixabay_background()
    except (requests.RequestException, RuntimeError, OSError) as e:
        print('Pixabay hatası:', e)
        fallback_background()
        return 'Generated abstract nature-inspired background'

def cards(t):
    values=[t['hook'],t['verse'],t['hadith'],t['advice']+'\nFaydalıysa paylaş.']
    fontfile='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font=ImageFont.truetype(fontfile,51)
    for i,value in enumerate(values):
        im=Image.new('RGBA',(1080,1920),(0,0,0,0)); d=ImageDraw.Draw(im)
        lines=[]
        for paragraph in value.splitlines(): lines.extend(textwrap.wrap(paragraph,28) or [''])
        y=(1920-85*len(lines))//2
        d.rounded_rectangle((45,y-65,1035,y+85*len(lines)+65),radius=35,fill=(0,0,0,190))
        for j,line in enumerate(lines): d.text((540,y+j*85),line,font=font,anchor='mt',fill='white')
        im.save(OUT/f'card{i}.png')
    return values

async def voices(values):
    durations=[]
    for i,v in enumerate(values):
        p=OUT/f'voice{i}.mp3'
        await edge_tts.Communicate(v,voice='tr-TR-AhmetNeural',rate='-8%').save(str(p))
        duration=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(p)],text=True).strip())
        durations.append(duration+0.5)
    return durations

def render(durations):
    for i,duration in enumerate(durations):
        subprocess.run(['ffmpeg','-y','-stream_loop','-1','-i',str(OUT/'nature.mp4'),'-loop','1','-i',str(OUT/f'card{i}.png'),'-i',str(OUT/f'voice{i}.mp3'),'-filter_complex','[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg];[bg][1:v]overlay=0:0[v]','-map','[v]','-map','2:a','-t',str(duration),'-r','25','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(OUT/f'part{i}.mp4')],check=True)
    (OUT/'concat.txt').write_text(''.join(f"file 'part{i}.mp4'\n" for i in range(len(durations))))
    subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(OUT/'concat.txt'),'-c','copy',str(OUT/'short.mp4')],check=True)

async def main():
    t=topic(); print('Konu:',t['name']); source=background(); values=cards(t); durations=await voices(values); render(durations)
    (OUT/'sources.json').write_text(json.dumps({'topic':t,'background':source,'status':'REQUIRES HUMAN VERIFICATION: verse/hadith citations and text'},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Taslak video: output/short.mp4 — yayınlamadan önce ayet ve hadis kaynaklarını doğrulayın.')

if __name__=='__main__': asyncio.run(main())
