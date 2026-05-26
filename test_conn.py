"""Test psycopg async connection."""
import asyncio
import psycopg

async def main():
    passwords = ["postgres", "admin123", "admin", "Lombardi2024"]
    for pwd in passwords:
        try:
            async with await psycopg.AsyncConnection.connect(
                host="127.0.0.1",
                port=5432,
                user="postgres",
                password=pwd,
                dbname="inventario",
                autocommit=True
            ) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT version()")
                    row = await cur.fetchone()
                    print(f"SUCCESS with '{pwd}': {row[0]}")
                    
                    # List tables
                    await cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
                    tables = await cur.fetchall()
                    print(f"Tables: {[t[0] for t in tables]}")
                    
                    # Check if users exist
                    try:
                        await cur.execute("SELECT usu_username, usu_rol, usu_estado FROM inv_usuario")
                        users = await cur.fetchall()
                        print(f"Users: {users}")
                    except Exception as ue:
                        print(f"No user table yet: {ue}")
                    return
        except Exception as e:
            print(f"FAILED with '{pwd}': {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
