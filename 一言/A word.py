# vocab.py
import os
import random
import time
import json
from datetime import datetime, date

# -------------------- 配置读写 --------------------
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), "settings.txt")

def load_settings():
    cfg = {"DAILY_NEW_LIMIT": "50", "TODAY_COUNT": "0", "TODAY_DATE": ""}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if "=" in ln:
                    k, v = ln.split("=", 1)
                    cfg[k.strip()] = v.strip().strip('"')
    return cfg

def save_settings(cfg):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        for k, v in cfg.items():
            f.write(f'{k} = "{v}"\n')

# -------------------- 文件管理 --------------------
class WordListManager:
    def __init__(self):
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.assets_dir = os.path.join(self.script_dir, "assets")
        os.makedirs(self.assets_dir, exist_ok=True)

    # 发现用户词表
    def find_user_wordlists(self):
        return [
            {"path": os.path.join(self.assets_dir, f),
             "name": os.path.splitext(f)[0]}
            for f in os.listdir(self.assets_dir)
            if f.endswith(".txt") and not f.startswith("_")
        ]

    # JSON 缓存路径
    def get_cache_file(self, wordlist_path):
        base = os.path.splitext(os.path.basename(wordlist_path))[0]
        return os.path.join(self.assets_dir, f"_{base}.json")

    # 读取词表 & JSON 缓存
    def load_wordlist(self, wordlist_path):
        cache = self.get_cache_file(wordlist_path)

        # 总单词数
        with open(wordlist_path, encoding="utf-8") as f:
            raw = [ln.strip() for ln in f if ln.strip()]
        total = len(raw)

        learned = []
        if os.path.exists(cache):
            try:
                with open(cache, encoding="utf-8") as f:
                    data = json.load(f).get("WORDLIST", [])
                learned = [
                    {
                        "word": w[0], "translation": w[1],
                        "ef": float(w[2]), "n": int(w[3]),
                        "interval": float(w[4]), "last_review": int(w[5])
                    }
                    for w in data
                ]
            except Exception:
                # 缓存损坏，重新生成
                pass
        return learned, total

    # 保存 JSON 缓存
    def save_wordlist(self, path, words):
        cache = self.get_cache_file(path)
        data = [[w["word"], w["translation"], w["ef"], w["n"], w["interval"], w["last_review"]] for w in words]
        with open(cache, "w", encoding="utf-8") as f:
            json.dump({"WORDLIST": data}, f, ensure_ascii=False, indent=0)

    # 重置进度
    def reset_wordlist(self, path):
        cache = self.get_cache_file(path)
        if os.path.exists(cache):
            os.remove(cache)
            return True
        return False

# -------------------- Anki/SM-2 算法 --------------------
class MemoryAlgorithm:
    @staticmethod
    def initial_ef():
        return 2.5

    @staticmethod
    def initial_interval(n):
        return [1, 6][min(n, 1)]

    @staticmethod
    def next_interval(prev_interval, ef):
        return prev_interval * ef

    @staticmethod
    def update_ef(ef, q):
        ef += 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
        return max(ef, 1.3)

    @staticmethod
    def review_weight(w, now):
        elapsed = (now - w["last_review"]) / (86400 * 1000)
        return elapsed / w["interval"] if w["interval"] > 0 else 1.0

# -------------------- 主程序 --------------------
class VocabularyApp:
    def __init__(self):
        self.mgr = WordListManager()
        self.wordlists = self.mgr.find_user_wordlists()
        self.curr = None
        self.words = []
        self._all_words = None
        self.total = 0
        self.idx = 0
        self.rand = False
        self.review_only = False

        self.cfg = load_settings()
        self.limit = int(self.cfg["DAILY_NEW_LIMIT"])
        self.today = str(date.today())
        self.today_count = int(self.cfg["TODAY_COUNT"])
        if self.cfg["TODAY_DATE"] != self.today:
            self.today_count = 0
            self.cfg["TODAY_DATE"] = self.today
            self.cfg["TODAY_COUNT"] = 0
            save_settings(self.cfg)

    @property
    def all_words(self):
        if self._all_words is None:
            self._load_all()
        return self._all_words

    def select_wordlist(self):
        if not self.wordlists:
            raise FileNotFoundError("未找到词表文件！")
        print("\n请选择词表:")
        for i, w in enumerate(self.wordlists, 1):
            print(f"{i}. {w['name']}")
        while True:
            ch = input("输入编号选择(或q退出): ").strip().lower()
            if ch == 'q':
                return False
            try:
                idx = int(ch) - 1
                if 0 <= idx < len(self.wordlists):
                    self.curr = self.wordlists[idx]
                    self.words, self.total = self.mgr.load_wordlist(self.curr['path'])
                    self._all_words = None
                    return True
                print("编号超出范围")
            except ValueError:
                print("请输入有效编号")

    def _load_all(self):
        if not self.curr:
            return
        with open(self.curr['path'], encoding='utf-8') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        self._all_words = [
            {"word": p[0], "translation": p[1], "is_learned": False}
            for ln in lines
            for p in [ln.split('\t') if '\t' in ln else ln.split(maxsplit=1)]
            if len(p) == 2
        ]
        learned_words = {w['word'] for w in self.words}
        for w in self._all_words:
            w['is_learned'] = w['word'] in learned_words

    def save(self):
        if not self.curr:
            return
        self.mgr.save_wordlist(self.curr['path'], self.words)
        save_settings(self.cfg)

    def get_word(self):
        if str(date.today()) != self.today:
            self.today = str(date.today())
            self.today_count = 0
            self.cfg["TODAY_DATE"] = self.today
            self.cfg["TODAY_COUNT"] = 0
            save_settings(self.cfg)

        now = int(time.time() * 1000)

        # 新词
        if not self.review_only and self.today_count < self.limit:
            unlearned = [w for w in self.all_words if not w["is_learned"]]
            if unlearned:
                w = random.choice(unlearned)
                new_word = {
                    "word": w["word"], "translation": w["translation"],
                    "ef": MemoryAlgorithm.initial_ef(), "n": 0,
                    "interval": 1, "last_review": now,
                    "is_new": True, "learn_date": str(date.today())
                }
                return {
                    "word": w["word"], "translation": w["translation"],
                    "is_new": True, "temp_new_word": new_word
                }

        # 复习
        if self.words:
            weights = [MemoryAlgorithm.review_weight(w, now) for w in self.words]
            self.idx = random.choices(range(len(self.words)), weights=weights)[0]
            return self.words[self.idx]

        if not self.words and self.all_words:
            return {"error": "no_learned_words"}
        return {"error": "no_words"}

    def answer(self, q: int):
        w = self.words[self.idx]
        now = int(time.time() * 1000)

        if q < 3:
            w["n"] = 0
            w["interval"] = MemoryAlgorithm.initial_interval(0)
        else:
            w["n"] += 1
            w["ef"] = MemoryAlgorithm.update_ef(w["ef"], q)
            if w["n"] == 1:
                w["interval"] = MemoryAlgorithm.initial_interval(1)
            else:
                w["interval"] = MemoryAlgorithm.next_interval(w["interval"], w["ef"])
        w["last_review"] = now
        w.pop("is_new", None)

    def flush(self):
        """立即写盘"""
        if self.curr:
            self.mgr.save_wordlist(self.curr['path'], self.words)
            save_settings(self.cfg)

# -------------------- UI --------------------
class UI:
    @staticmethod
    def cls():
        os.system('cls' if os.name == 'nt' else 'clear')

    @staticmethod
    def banner(app):
        UI.cls()
        print("📚 智能背单词系统（Anki/SM-2）")
        print("====================")
        if app.curr:
            learned = len(app.words)
            print(f"当前词典: {app.curr['name']} ({learned}/{app.total})")
            mode_text = "复习" if app.review_only else ("随机" if app.rand else "顺序")
            print(f"模式: {mode_text}")
            print(f"今日已学新词: {app.today_count}/{app.limit}")

        r_hint = "随机" if not app.rand else "顺序"
        m_hint = "复习" if not app.review_only else "学习"
        print("====================")
        print("操作指南:")
        print("  u - 认识单词（跳过解释）")
        print("  d - 显示解释")
        print("  s - 统计")
        print(f"  r - 切换{r_hint}模式")
        print(f"  m - 切换{m_hint}")
        print("  c - 选择词典")
        print("  x - 重置进度")
        print("  q - 保存退出")
        print("====================")

    @staticmethod
    def word(w):
        if w is None:
            print("\n⚠️ 没有获取到单词数据")
            return None
        if "error" in w:
            if w["error"] == "no_words":
                print("\n⚠️ 当前词典没有学习记录")
            elif w["error"] == "no_learned_words":
                print("\n⚠️ 当前词典没有已学单词")
            return None
        if w.get("is_new"):
            print(f"\n✨ 新单词: {w['word']}")
        else:
            print(f"\n复习单词: {w['word']}")
        while True:
            act = input("输入 u=认识 / d=显示解释: ").lower()
            if act in {'u', 'd', 's', 'r', 'm', 'c', 'x', 'q'}:
                return act
            print("⚠️ 请输入有效的选项(u/d/s/r/m/c/x/q)！")

    @staticmethod
    def explain(w):
        if "error" in w:
            return None
        if w.get("is_new"):
            print(f"\n✨ 新单词: {w['word']}")
            print(f"🔍 解释: {w['translation']}")
            input("\n按回车键继续...")
            return 0
        print(f"\n复习单词: {w['word']}")
        print(f"🔍 解释: {w['translation']}")
        print(f"📈 易记因子 EF: {w['ef']:.2f}")
        print(f"⏱️ 间隔天数: {w['interval']:.1f}")
        last = datetime.fromtimestamp(w["last_review"] / 1000)
        hrs = (time.time() - w["last_review"] / 1000) / 3600
        info = f"{int(hrs / 24)}天前" if hrs > 48 else f"{int(hrs)}小时前" if hrs > 1 else "刚刚"
        print(f"⏱️ 上次复习: {last.strftime('%Y-%m-%d %H:%M')} ({info})")
        while True:
            try:
                q = int(input("\n回忆质量 (0 完全忘记 … 5 秒答): "))
                if 0 <= q <= 5:
                    return q
                print("⚠️ 请输入0-5之间的整数！")
            except ValueError:
                print("⚠️ 请输入有效的数字(0-5)！")

    @staticmethod
    def stats(app):
        app.save()          # 先落盘
        mgr = WordListManager()
        wordlists = mgr.find_user_wordlists()
        if not wordlists:
            print("\n📚 词典学习进度:")
            print("未找到任何词表文件。")
            input("\n按回车继续...")
            return

        print("\n📚 词典学习进度:")
        # 新表头：已学占比 + 已学掌握率
        print(f"{'词典名称':<18}{'已学/总数':<12}{'已学占比':<10}{'已学掌握率':<10}")
        print("-" * 52)
        for wl in wordlists:
            try:
                learned, total = mgr.load_wordlist(wl['path'])
                if total == 0:
                    continue
                learned_cnt = len(learned)
                known_cnt   = sum(1 for w in learned if w["interval"] >= 21)

                learned_ratio = learned_cnt / total * 100
                mastery_ratio = known_cnt / learned_cnt * 100 if learned_cnt else 0.0

                print(f"{wl['name']:<18}"
                      f"{learned_cnt}/{total:<11}"
                      f"{learned_ratio:>6.1f}%    "
                      f"{mastery_ratio:>6.1f}%")
            except Exception:
                continue
        input("\n按回车继续...")

    @staticmethod
    def confirm_reset(wordlist_name):
        print(f"\n⚠️ 即将重置词表: {wordlist_name}")
        print("⚠️ 此操作将删除所有学习记录且不可恢复！")
        while True:
            confirm = input("确认重置吗？(y/n): ").lower()
            if confirm == 'y':
                return True
            elif confirm == 'n':
                return False
            print("请输入 y 或 n")

# -------------------- main --------------------
def main():
    try:
        app = VocabularyApp()
        if not app.select_wordlist():
            return
        while True:
            UI.banner(app)
            w = app.get_word()
            if w and "error" in w and w["error"] == "no_learned_words":
                print("\n⚠️ 当前词典没有已学单词")
                input("按回车键返回学习模式...")
                app.review_only = False
                continue
            if not w or "error" in w:
                UI.word(w)
                time.sleep(1.5)
                continue
            act = UI.word(w)
            if act == 'u':
                q = 5
                if w.get("temp_new_word"):
                    new_word = w["temp_new_word"]
                    app.words.append(new_word)
                    app.idx = len(app.words) - 1
                    for a in app.all_words:
                        if a["word"] == new_word["word"]:
                            a["is_learned"] = True
                            break
                    app.today_count += 1
                    app.cfg["TODAY_COUNT"] = app.today_count
                    save_settings(app.cfg)
                app.answer(q)
                app.flush()
            elif act == 'd':
                q = UI.explain(w)
                if q is None:
                    continue
                if w.get("temp_new_word"):
                    new_word = w["temp_new_word"]
                    app.words.append(new_word)
                    app.idx = len(app.words) - 1
                    for a in app.all_words:
                        if a["word"] == new_word["word"]:
                            a["is_learned"] = True
                            break
                    app.today_count += 1
                    app.cfg["TODAY_COUNT"] = app.today_count
                    save_settings(app.cfg)
                app.answer(q)
                app.flush()
            elif act == 's':
                UI.stats(app)
            elif act == 'r':
                app.rand = not app.rand
                time.sleep(0.8)
            elif act == 'm':
                app.review_only = not app.review_only
                time.sleep(0.8)
            elif act == 'c':
                app.save()
                if app.select_wordlist():
                    continue
                else:
                    break
            elif act == 'x':
                if app.curr:
                    if UI.confirm_reset(app.curr['name']):
                        if app.mgr.reset_wordlist(app.curr['path']):
                            app.words, app.total = app.mgr.load_wordlist(app.curr['path'])
                            app._all_words = None
                            print(f"\n✅ 已重置词表: {app.curr['name']}")
                            time.sleep(1)
                else:
                    print("\n⚠️ 请先选择词表！")
                    time.sleep(1)
            elif act == 'q':
                app.save()
                print("\n💾 学习进度已保存！")
                break
            else:
                app.answer(0)
                app.flush()
    except KeyboardInterrupt:
        try:
            app.save()
        except:
            pass
        print("\n💾 已强制保存，bye~")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        input("\n按回车退出...")

if __name__ == "__main__":
    main()