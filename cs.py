from fissures import run_update_process
import asyncio
if __name__ == "__main__":
    result = asyncio.run(run_update_process())
    print("测试结果:", result)
