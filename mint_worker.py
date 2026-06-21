import sys
import app as appmod
if __name__ == '__main__':
    appmod.init_db()
    appmod.ensure_seed_pool()
    print("CC·STAMP mint worker 启动（独立进程，单实例）", flush=True)
    appmod._mint_worker_loop()
