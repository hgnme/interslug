import asyncio
from dataclasses import dataclass
import time
from .frames import QueuedFrame, ReturnFrame, create_zero_frame
from logging_config import get_logger


@dataclass 
class Queue():
    """
        Stores a Queue with an Identifier
    """
    id_str: str
    queue: asyncio.Queue

@dataclass
class QueueListType():
    type_name: str
    queues: list[Queue]


logger = get_logger("queue-helpers")

MASTER_QUEUE_LIST: list[QueueListType] = []

Q_LIST_TYPE_SIP_TO_BROWSER = "Q_LIST_SIP_TO_BROWSER"
Q_LIST_TYPE_BROWSER_TO_SIP = "Q_LIST_BROWSER_TO_SIP"

def get_queue_list_by_type(type_name: str) -> QueueListType:
    global MASTER_QUEUE_LIST
    for qlt in MASTER_QUEUE_LIST:
        if qlt.type_name == type_name:
            return qlt
    logger.debug(f"Creating Queue List {type_name}")
    qlt = QueueListType(type_name, [])
    MASTER_QUEUE_LIST.append(qlt)
    return qlt

def get_queue_by_id(queue_list: QueueListType, id_str: str) -> Queue:
    for queue in queue_list.queues:
        if queue.id_str == id_str:
            return queue
        
    logger.debug(f"Creating Queue id_str={id_str} in queue_list={queue_list.type_name}")
    queue = Queue(id_str, asyncio.Queue(maxsize=5))
    queue_list.queues.append(queue)
    return queue

def add_frame_to_queue(audio_data, queue: Queue):
    """
        Add a Frame to a given queue with a timestamp to track age
    """
    obj = QueuedFrame(audio_data, len(audio_data), time.time())
    
    queue.queue.put_nowait(obj)
async def get_from_queue(queue: Queue, max_age: float, expected_sample_size: int):
    """
        Retrieve the first Frame from a given Queue, which is younger than the max_age (in seconds). 
        If no frame is found, a "Zero" frame is returned in the length provided (expected_sample_size)
    """
    logger = get_logger("get_from_queue")
    now = time.time()
    while not queue.queue.empty():
        frame: QueuedFrame = await queue.queue.get()
        return_frame = ReturnFrame(frame.audio_data, frame.samples, frame.timestamp_added)
        return_frame.age_in_sec = now - return_frame.timestamp_added
        if return_frame.age_in_sec <= max_age:
            # Frame is within the cutoff, so it is output
            return return_frame
        else: 
            logger.debug(f"Dropping frame due to excessive age. cutoff={max_age}s, actual={return_frame.age_in_sec}s")
    
    # logger.debug(f"Returning zero frame due to empty queue")
    return create_zero_frame(expected_sample_size)