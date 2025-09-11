from typing import Any, Dict, Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


MONGO_URI_ENV = "mongodb://mongo:27017"
DEFAULT_DB_NAME = "psp_local"


class MongoConnection:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None

    @classmethod
    async def init(cls, mongo_uri: str, db_name: str = DEFAULT_DB_NAME) -> None:
        cls.client = AsyncIOMotorClient(mongo_uri)
        cls.db = cls.client[db_name]
        await cls._ensure_indexes()

    @classmethod
    async def close(cls) -> None:
        if cls.client:
            cls.client.close()
        cls.client = None
        cls.db = None

    @classmethod
    async def _ensure_indexes(cls) -> None:
        if cls.db is None:
            return
        await cls.db.proteins.create_index("accession", unique=True)
        await cls.db.tasks.create_index("status")
        await cls.db.tasks.create_index("created_at")
        await cls.db.protein_results.create_index("accession", unique=True)


async def upsert_protein(doc: Dict[str, Any]) -> None:

    if MongoConnection.db is None:
        raise RuntimeError("Mongo not initialized")
    accession = doc.get("accession")
    if not accession:
        raise ValueError("protein doc requires 'accession'")

    await MongoConnection.db.proteins.update_one(
        {"accession": accession},
        {"$set": doc},
        upsert=True,
    )


async def get_protein(accession: str) -> Optional[Dict[str, Any]]:
    if MongoConnection.db is None:
        raise RuntimeError("Mongo not initialized")
    return await MongoConnection.db.proteins.find_one({"accession": accession}, {"_id": 0})


async def insert_task(task: Dict[str, Any]) -> str:
    if MongoConnection.db is None:
        raise RuntimeError("Mongo not initialized")
    result = await MongoConnection.db.tasks.insert_one(task)
    return str(result.inserted_id)


async def update_task(task_id: Any, fields: Dict[str, Any]) -> None:
    if MongoConnection.db is None:
        raise RuntimeError("Mongo not initialized")
    await MongoConnection.db.tasks.update_one({"_id": task_id}, {"$set": fields})


async def upsert_aggregate(accession: str, aggregate: Dict[str, Any]) -> None:
    if MongoConnection.db is None:
        raise RuntimeError("Mongo not initialized")
    await MongoConnection.db.aggregates.update_one(
        {"accession": accession},
        {"$set": {"accession": accession, "data": aggregate}},
        upsert=True,
    )


async def upsert_processed(accession: str, processed: Dict[str, Any]) -> None:
    if MongoConnection.db is None:
        raise RuntimeError("Mongo not initialized")
    await MongoConnection.db.processed.update_one(
        {"accession": accession},
        {"$set": {"accession": accession, "processed": processed}},
        upsert=True,
    )


async def upsert_protein_result(accession: str, output_doc: Dict[str, Any]) -> None:
    if MongoConnection.db is None:
        raise RuntimeError("Mongo not initialized")
    await MongoConnection.db.protein_results.update_one(
        {"accession": accession},
        {"$set": output_doc},
        upsert=True,
    )


async def get_protein_result(accession: str) -> Optional[Dict[str, Any]]:
    if MongoConnection.db is None:
        raise RuntimeError("Mongo not initialized")
    return await MongoConnection.db.protein_results.find_one({"accession": accession}, {"_id": 0})

