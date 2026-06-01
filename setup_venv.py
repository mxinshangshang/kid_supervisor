#!/usr/bin/env python3
"""
设置 Python 3.11 venv 用于 mediapipe 推理
"""
import sys
import os
import subprocess
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(BASE_DIR, "venv_311")
REQUIREMENTS = os.path.join(BASE_DIR, "requirements-inference.txt")

def run_cmd(cmd, cwd=None):
    """运行命令"""
    print(f"$ {cmd}")
    return subprocess.run(cmd, shell=True, cwd=cwd)

def main():
    print("=" * 60)
    print("🔧 Kid Supervisor - 环境设置")
    print("=" * 60)

    # 检查系统 Python 版本
    print(f"\n[1/4] 检查系统 Python...")
    result = subprocess.run(["/usr/bin/python3", "--version"], capture_output=True, text=True)
    print(f"    系统 Python: {result.stdout.strip()}")

    # 检查 Python 3.11 是否可用
    print(f"\n[2/4] 查找 Python 3.11...")
    python311 = None

    # 尝试几个可能的路径
    candidates = [
        "python3.11",
        "/usr/bin/python3.11",
        "/usr/local/bin/python3.11",
        os.path.expanduser("~/.pyenv/versions/3.11.*/bin/python"),
    ]

    for candidate in candidates:
        if "*" in candidate:
            import glob
            matches = glob.glob(candidate)
            if matches:
                python311 = matches[0]
                break
        else:
            result = subprocess.run(["which", candidate], capture_output=True, text=True)
            if result.returncode == 0:
                python311 = result.stdout.strip()
                break

    if not python311:
        print("    ❌ 未找到 Python 3.11")
        print("\n请先安装 Python 3.11:")
        print("  方案 1 (推荐): 使用 pyenv")
        print("    curl https://pyenv.run | bash")
        print('    echo \'export PYENV_ROOT="$HOME/.pyenv"\' >> ~/.bashrc')
        print('    echo \'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"\' >> ~/.bashrc')
        print('    echo \'eval "$(pyenv init -)"\' >> ~/.bashrc')
        print("    然后重启终端，运行:")
        print("    pyenv install 3.11.9")
        print("    pyenv global 3.11.9")
        print("\n  方案 2: 使用 apt (Debian/Ubuntu)")
        print("    sudo apt update")
        print("    sudo apt install software-properties-common")
        print("    sudo add-apt-repository ppa:deadsnakes/ppa")
        print("    sudo apt update")
        print("    sudo apt install python3.11 python3.11-venv python3.11-dev")
        return 1

    print(f"    ✅ 找到: {python311}")

    # 创建 venv
    print(f"\n[3/4] 创建 venv...")
    if os.path.exists(VENV_DIR):
        print(f"    旧 venv 已存在，删除中...")
        shutil.rmtree(VENV_DIR)

    result = run_cmd(f'"{python311}" -m venv "{VENV_DIR}"')
    if result.returncode != 0:
        print("    ❌ venv 创建失败")
        return 1
    print(f"    ✅ venv 已创建: {VENV_DIR}")

    # 安装依赖
    print(f"\n[4/4] 安装依赖...")
    pip_path = os.path.join(VENV_DIR, "bin", "pip")
    result = run_cmd(f'"{pip_path}" install --upgrade pip')
    result = run_cmd(f'"{pip_path}" install -r "{REQUIREMENTS}"')
    if result.returncode != 0:
        print("    ❌ 依赖安装失败")
        return 1
    print(f"    ✅ 依赖安装完成")

    print("\n" + "=" * 60)
    print("✅ 环境设置完成！")
    print("=" * 60)
    print("\n现在可以运行:")
    print("  ./start.sh")
    print("或:")
    print("  python3 main.py")
    print("\n")

    return 0

if __name__ == "__main__":
    sys.exit(main())
