import os
import shutil
from flask import Flask, render_template_string, send_from_directory, request, jsonify, abort

app = Flask(__name__)

# Папка, где расположен main.py (тут лежат "сырые" скачанные фото)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Путь до rp_media считаем от BASE_DIR:
#   BASE_DIR      = .../TgBot/Photos_not/photos
#   TGBOT_DIR     = .../TgBot
#   RP_MEDIA_DIR  = .../TgBot/webpanel/static/rp_media
# Если разложите скрипт в другое место — просто пропишите RP_MEDIA_DIR руками.
TGBOT_DIR = os.path.dirname(os.path.dirname(BASE_DIR))
RP_MEDIA_DIR = os.path.join(TGBOT_DIR, "webpanel", "static", "rp_media")

# Поддерживаемые расширения
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.svg'}

# Категории жестов и подпапки по составу пары — как в README
CATEGORIES = {
    "hugs":   "Обнять",
    "kisses": "Поцеловать",
    "bites":  "Кусь",
    "spanks": "Шлёп",
    "smacks": "Уебать",
}
PAIR_TYPES = {
    "mf": "Парень + Девушка (действие делает парень)",
    "fm": "Девушка + Парень (действие делает девушка)",
    "mm": "Парень + Парень",
    "ff": "Девушка + Девушка",
}


def get_images():
    """Сканирует BASE_DIR и возвращает список всех найденных картинок"""
    images = []
    try:
        all_items = os.listdir(BASE_DIR)
        for item in all_items:
            full_path = os.path.join(BASE_DIR, item)
            ext = os.path.splitext(item)[1].lower()
            if ext in IMAGE_EXTENSIONS and os.path.isfile(full_path):
                images.append(item)
        images.sort()
    except Exception as e:
        print(f"Ошибка при чтении папки: {e}")

    return images


def safe_filename(filename):
    """Не даём выйти за пределы BASE_DIR через '../' и т.п."""
    name = os.path.basename(filename)
    if not name or name != filename.replace("\\", "/").split("/")[-1] or name in (".", ".."):
        return None
    return name


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Галерея Фотографий</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, -apple-system, sans-serif; background-color: #121212; color: #fff; padding: 20px; }
        h1 { text-align: center; margin-bottom: 20px; font-size: 24px; }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
            gap: 12px;
        }
        .card { position: relative; }
        .grid img {
            width: 100%;
            height: 160px;
            object-fit: cover;
            border-radius: 8px;
            cursor: pointer;
            transition: transform 0.2s;
            background-color: #222;
            display: block;
        }
        .grid img:hover { transform: scale(1.03); }

        .modal {
            display: none;
            position: fixed;
            z-index: 1000;
            top: 0; left: 0; width: 100%; height: 100%;
            background-color: rgba(0, 0, 0, 0.92);
            justify-content: center;
            align-items: center;
            flex-direction: column;
        }
        .modal-content {
            max-width: 95%;
            max-height: 70vh;
            border-radius: 6px;
            object-fit: contain;
        }
        .close {
            position: absolute;
            top: 15px; right: 25px;
            color: #fff; font-size: 35px; font-weight: bold;
            cursor: pointer; z-index: 1001;
        }
        .prev, .next {
            position: absolute;
            top: 45%; transform: translateY(-50%);
            color: white; font-size: 30px; font-weight: bold;
            padding: 12px 18px; cursor: pointer;
            user-select: none; background: rgba(255,255,255,0.1);
            border-radius: 50%; border: none; z-index: 1001;
        }
        .prev { left: 15px; }
        .next { right: 15px; }
        .prev:hover, .next:hover { background: rgba(255,255,255,0.3); }
        .counter {
            margin-top: 10px; color: #ccc; font-size: 14px;
        }

        .toolbar {
            margin-top: 18px;
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
            justify-content: center;
            background: rgba(255,255,255,0.06);
            padding: 12px 16px;
            border-radius: 10px;
        }
        .toolbar select, .toolbar button {
            font-size: 14px;
            padding: 8px 12px;
            border-radius: 6px;
            border: none;
            cursor: pointer;
        }
        .toolbar select { background: #2a2a2a; color: #fff; }
        .btn-move { background: #2d7dfb; color: #fff; }
        .btn-move:hover { background: #1f63d1; }
        .btn-delete { background: #e0453f; color: #fff; }
        .btn-delete:hover { background: #bd332e; }
        .status { margin-top: 8px; font-size: 13px; min-height: 18px; color: #9fdf9f; }
        .status.error { color: #ff8b85; }
    </style>
</head>
<body>

    <h1>📸 Найдено фото: <span id="total-count">{{ images|length }}</span></h1>

    <div class="grid" id="grid">
        {% for img in images %}
            <div class="card" data-filename="{{ img }}">
                <img src="/photo/{{ img }}" onclick="openModal({{ loop.index0 }})" alt="{{ img }}" loading="lazy">
            </div>
        {% endfor %}
    </div>

    <div id="lightbox" class="modal">
        <span class="close" onclick="closeModal()">&times;</span>
        <button class="prev" onclick="changeSlide(-1)">&#10094;</button>
        <img id="modal-img" class="modal-content" src="" alt="Full Photo">
        <button class="next" onclick="changeSlide(1)">&#10095;</button>
        <div id="counter" class="counter"></div>

        <div class="toolbar">
            <select id="category-select" onchange="updatePairOptions()"></select>
            <select id="pair-select"></select>
            <button class="btn-move" onclick="moveCurrent()">📤 Переместить</button>
            <button class="btn-delete" onclick="deleteCurrent()">🗑 Удалить</button>
        </div>
        <div id="status" class="status"></div>
    </div>

    <script>
        let images = {{ images | tojson }};
        let currentIndex = 0;

        const CATEGORIES = {{ categories | tojson }};
        const PAIR_TYPES = {{ pair_types | tojson }};

        function populateSelects() {
            const catSel = document.getElementById('category-select');
            catSel.innerHTML = '';
            for (const [key, label] of Object.entries(CATEGORIES)) {
                const opt = document.createElement('option');
                opt.value = key;
                opt.textContent = label;
                catSel.appendChild(opt);
            }
            updatePairOptions();
        }

        function updatePairOptions() {
            const pairSel = document.getElementById('pair-select');
            pairSel.innerHTML = '';
            for (const [key, label] of Object.entries(PAIR_TYPES)) {
                const opt = document.createElement('option');
                opt.value = key;
                opt.textContent = label;
                pairSel.appendChild(opt);
            }
        }

        function openModal(index) {
            currentIndex = index;
            document.getElementById('lightbox').style.display = 'flex';
            setStatus('');
            updateModalImage();
        }

        function closeModal() {
            document.getElementById('lightbox').style.display = 'none';
        }

        function changeSlide(direction) {
            if (images.length === 0) return;
            currentIndex += direction;
            if (currentIndex < 0) currentIndex = images.length - 1;
            if (currentIndex >= images.length) currentIndex = 0;
            setStatus('');
            updateModalImage();
        }

        function updateModalImage() {
            if (images.length === 0) {
                closeModal();
                return;
            }
            document.getElementById('modal-img').src = '/photo/' + encodeURIComponent(images[currentIndex]);
            document.getElementById('counter').innerText = (currentIndex + 1) + ' / ' + images.length;
        }

        function setStatus(msg, isError) {
            const el = document.getElementById('status');
            el.textContent = msg;
            el.className = 'status' + (isError ? ' error' : '');
        }

        function removeFromGrid(filename) {
            const card = document.querySelector('.card[data-filename="' + CSS.escape(filename) + '"]');
            if (card) card.remove();
            images = images.filter(f => f !== filename);
            document.getElementById('total-count').textContent = images.length;
        }

        async function deleteCurrent() {
            if (images.length === 0) return;
            const filename = images[currentIndex];
            setStatus('Удаляем...');
            try {
                const res = await fetch('/delete/' + encodeURIComponent(filename), { method: 'POST' });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || 'Ошибка удаления');

                removeFromGrid(filename);
                setStatus('Удалено: ' + filename);
                if (images.length === 0) { closeModal(); return; }
                if (currentIndex >= images.length) currentIndex = images.length - 1;
                updateModalImage();
            } catch (err) {
                setStatus(err.message, true);
            }
        }

        async function moveCurrent() {
            if (images.length === 0) return;
            const filename = images[currentIndex];
            const category = document.getElementById('category-select').value;
            const pair = document.getElementById('pair-select').value;

            setStatus('Перемещаем...');
            try {
                const res = await fetch('/move/' + encodeURIComponent(filename), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category, pair })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || 'Ошибка перемещения');

                removeFromGrid(filename);
                setStatus('Перемещено в ' + CATEGORIES[category] + ' / ' + PAIR_TYPES[pair] + (data.renamed ? ' (переименовано в ' + data.saved_as + ', т.к. файл с таким именем уже был)' : ''));
                if (images.length === 0) { closeModal(); return; }
                if (currentIndex >= images.length) currentIndex = images.length - 1;
                updateModalImage();
            } catch (err) {
                setStatus(err.message, true);
            }
        }

        document.addEventListener('keydown', function(event) {
            const modal = document.getElementById('lightbox');
            if (modal.style.display === 'flex') {
                if (event.key === 'ArrowLeft') changeSlide(-1);
                if (event.key === 'ArrowRight') changeSlide(1);
                if (event.key === 'Escape') closeModal();
                if (event.key === 'Delete') deleteCurrent();
            }
        });

        populateSelects();
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    images = get_images()
    return render_template_string(
        HTML_TEMPLATE,
        images=images,
        categories=CATEGORIES,
        pair_types=PAIR_TYPES,
    )


@app.route('/photo/<path:filename>')
def serve_photo(filename):
    return send_from_directory(BASE_DIR, filename)


@app.route('/delete/<path:filename>', methods=['POST'])
def delete_photo(filename):
    name = safe_filename(filename)
    if not name:
        return jsonify(ok=False, error='Некорректное имя файла'), 400

    full_path = os.path.join(BASE_DIR, name)
    if not os.path.isfile(full_path):
        return jsonify(ok=False, error='Файл не найден'), 404

    try:
        os.remove(full_path)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True)


@app.route('/move/<path:filename>', methods=['POST'])
def move_photo(filename):
    name = safe_filename(filename)
    if not name:
        return jsonify(ok=False, error='Некорректное имя файла'), 400

    data = request.get_json(silent=True) or {}
    category = data.get('category')
    pair = data.get('pair')

    if category not in CATEGORIES:
        return jsonify(ok=False, error='Неизвестная категория жеста'), 400
    if pair not in PAIR_TYPES:
        return jsonify(ok=False, error='Неизвестный состав пары'), 400

    src_path = os.path.join(BASE_DIR, name)
    if not os.path.isfile(src_path):
        return jsonify(ok=False, error='Файл не найден'), 404

    dest_dir = os.path.join(RP_MEDIA_DIR, category, pair)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except Exception as e:
        return jsonify(ok=False, error=f'Не удалось создать папку назначения: {e}'), 500

    dest_name = name
    dest_path = os.path.join(dest_dir, dest_name)

    renamed = False
    if os.path.exists(dest_path):
        # файл с таким именем уже есть в папке назначения — не перезаписываем,
        # добавляем числовой суффикс
        base, ext = os.path.splitext(name)
        i = 1
        while True:
            candidate = f"{base}_{i}{ext}"
            candidate_path = os.path.join(dest_dir, candidate)
            if not os.path.exists(candidate_path):
                dest_name = candidate
                dest_path = candidate_path
                renamed = True
                break
            i += 1

    try:
        shutil.move(src_path, dest_path)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

    return jsonify(ok=True, saved_as=dest_name, renamed=renamed)


if __name__ == '__main__':
    print(f"BASE_DIR (сырые фото):   {BASE_DIR}")
    print(f"RP_MEDIA_DIR (назначение): {RP_MEDIA_DIR}")
    get_images()
    app.run(host='0.0.0.0', port=5000, debug=True)
