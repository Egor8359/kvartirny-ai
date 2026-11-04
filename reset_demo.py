"""Stop the server before running this command. No files are deleted."""
from app.database import make_engine, Base, initialize, environment

if __name__ == '__main__':
    print('ВНИМАНИЕ: будут удалены все пользователи, сессии, диалоги и факты демонстрационной базы.')
    print('Сначала остановите сервер. Для подтверждения введите: RESET DEMO')
    if input('> ').strip() != 'RESET DEMO':
        raise SystemExit('Сброс отменён.')
    engine = make_engine()
    if engine.dialect.name != 'sqlite' or environment() != 'development':
        raise SystemExit('Сброс разрешён только для локальной SQLite в development.')
    Base.metadata.drop_all(engine)
    initialize(engine)
    engine.dispose()
    print('Демонстрационная база пересоздана. История и память пусты.')
