SNIPPETS = [
    {
        "id": "hello",
        "title": "Hello World",
        "description": "Sanity check — instant output",
        "code": 'print("Hello from your sandbox!")\nprint("Sandbox is isolated and ready.")',
    },
    {
        "id": "fibonacci",
        "title": "Fibonacci",
        "description": "Compute with memoization",
        "code": (
            "from functools import lru_cache\n\n"
            "@lru_cache(maxsize=None)\n"
            "def fib(n):\n"
            "    return n if n < 2 else fib(n-1) + fib(n-2)\n\n"
            "for i in range(15):\n"
            "    print(f'fib({i}) = {fib(i)}')"
        ),
    },
    {
        "id": "files",
        "title": "Write & Read Files",
        "description": "Files persist in your sandbox workspace",
        "code": (
            "import os\n\n"
            "# Write three files\n"
            "for i in range(1, 4):\n"
            "    with open(f'note_{i}.txt', 'w') as f:\n"
            "        f.write(f'Note {i}: sandbox file storage works!\\n')\n\n"
            "# Read them back\n"
            "for name in sorted(os.listdir('.')):\n"
            "    with open(name) as f:\n"
            "        print(f'{name}: {f.read().strip()}')"
        ),
    },
    {
        "id": "fetch",
        "title": "Fetch a URL",
        "description": "Network egress from inside the sandbox",
        "code": (
            "import urllib.request\n\n"
            "url = 'http://example.com'\n"
            "with urllib.request.urlopen(url, timeout=8) as r:\n"
            "    body = r.read().decode()\n"
            "    lines = [l for l in body.splitlines() if l.strip()][:6]\n"
            "    print(f'Status: {r.status}')\n"
            "    print('First 6 non-empty lines:')\n"
            "    for line in lines:\n"
            "        print(' ', line)"
        ),
    },
    {
        "id": "pip_install",
        "title": "Install a Package",
        "description": "pip install works — packages persist while sandbox is alive",
        "code": (
            "import subprocess, sys, importlib\n\n"
            "print('Installing cowsay...')\n"
            "result = subprocess.run(\n"
            "    [sys.executable, '-m', 'pip', 'install', 'cowsay', '-q'],\n"
            "    capture_output=True, text=True\n"
            ")\n"
            "print(result.stdout or '(installed)')\n\n"
            "# Refresh the import cache so the freshly installed package is visible\n"
            "importlib.invalidate_caches()\n\n"
            "import cowsay\n"
            "cowsay.cow('Hello from a freshly installed package!')"
        ),
    },
    {
        "id": "data",
        "title": "Data Processing",
        "description": "Parse CSV, compute stats, write result file",
        "code": (
            "import csv, io, statistics\n\n"
            "raw = '''name,score\\nAlice,92\\nBob,87\\nCarol,95\\nDave,78\\nEve,91'''\n\n"
            "rows = list(csv.DictReader(io.StringIO(raw)))\n"
            "scores = [int(r['score']) for r in rows]\n"
            "stats = {\n"
            "    'count': len(scores),\n"
            "    'mean': statistics.mean(scores),\n"
            "    'median': statistics.median(scores),\n"
            "    'stdev': round(statistics.stdev(scores), 2),\n"
            "    'min': min(scores),\n"
            "    'max': max(scores),\n"
            "}\n"
            "for k, v in stats.items():\n"
            "    print(f'{k:8}: {v}')\n\n"
            "with open('stats.csv', 'w') as f:\n"
            "    f.write(','.join(stats.keys()) + '\\n')\n"
            "    f.write(','.join(str(v) for v in stats.values()) + '\\n')\n"
            "print('\\nWrote stats.csv to workspace')"
        ),
    },
]
