=======================================
Enhance Reliability of Asynchronous Job
=======================================

Background
==========

Currently we are using cast method in our RPC client to trigger asynchronous
job in XJob daemon. After one of the worker threads receives the RPC message
from the message broker, it registers the job in the database and starts to
run the handle function. The registration guarantees that asynchronous job will
not be lost after the job fails and the failed job can be redone. The detailed
discussion of the asynchronous job process in XJob daemon is covered in our
design document [1]_.

Though asynchronous jobs are correctly saved after worker threads get the RPC
message, we still have risk to lose jobs. By using cast method, it's only
guaranteed that the message is received by the message broker, but there's no
guarantee that the message can be received by the message consumer, i.e., the
RPC server thread running in XJob daemon. According to the RabbitMQ document,
undelivered messages will be lost if RabbitMQ server stops [2]_. Message
persistence or publisher confirm [3]_ can be used to increase reliability, but
they sacrifice performance. On the other hand, we can not assume that message
brokers other than RabbitMQ will provide similar persistence or confirmation
functionality. Therefore, Tricircle itself should handle the asynchronous job
reliability problem as far as possible. Since we already have a framework to
register, run and redo asynchronous jobs in XJob daemon, we propose a cheaper
way to improve reliability.

Proposal
========

One straightforward way to make sure that the RPC server has received the RPC
message is to use call method. RPC client will be blocked until the RPC server
replies the message if it uses call method to send the RPC request. So if
something wrong happens before the reply, RPC client can be aware of it. Of
course we cannot make RPC client wait too long, thus RPC handlers in the RPC
server side need to be simple and quick to run. Thanks to the asynchronous job
framework we already have, migrating from cast method to call method is easy.

Here is the flow of the current process::

  +--------+     +--------+         +---------+     +---------------+   +----------+
  |        |     |        |         |         |     |               |   |          |
  | API    |     | RPC    |         | Message |     | RPC Server    |   | Database |
  | Server |     | client |         | Broker  |     | Handle Worker |   |          |
  |        |     |        |         |         |     |               |   |          |
  +---+----+     +---+----+         +----+----+     +-------+-------+   +----+-----+
      |              |                   |                  |                |
      | call RPC API |                   |                  |                |
      +-------------->                   |                  |                |
      |              | send cast message |                  |                |
      |              +------------------->                  |                |
      | call return  |                   | dispatch message |                |
      <--------------+                   +------------------>                |
      |              |                   |                  | register job   |
      |              |                   |                  +---------------->
      |              |                   |                  |                |
      |              |                   |                  | obtain lock    |
      |              |                   |                  +---------------->
      |              |                   |                  |                |
      |              |                   |                  | run job        |
      |              |                   |                  +----+           |
      |              |                   |                  |    |           |
      |              |                   |                  |    |           |
      |              |                   |                  <----+           |
      |              |                   |                  |                |
      |              |                   |                  |                |
      +              +                   +                  +                +

We can just leave **register job** phase in the RPC handle and put **obtain
lock** and **run job** phase in a separate thread, so the RPC handle is simple
enough to use call method to invoke it. Here is the proposed flow::

  +--------+     +--------+          +---------+     +---------------+   +----------+   +-------------+   +-------+
  |        |     |        |          |         |     |               |   |          |   |             |   |       |
  | API    |     | RPC    |          | Message |     | RPC Server    |   | Database |   | RPC Server  |   | Job   |
  | Server |     | client |          | Broker  |     | Handle Worker |   |          |   | Loop Worker |   | Queue |
  |        |     |        |          |         |     |               |   |          |   |             |   |       |
  +---+----+     +---+----+          +----+----+     +-------+-------+   +----+-----+   +------+------+   +---+---+
      |              |                    |                  |                |                |              |
      | call RPC API |                    |                  |                |                |              |
      +-------------->                    |                  |                |                |              |
      |              | send call message  |                  |                |                |              |
      |              +-------------------->                  |                |                |              |
      |              |                    | dispatch message |                |                |              |
      |              |                    +------------------>                |                |              |
      |              |                    |                  | register job   |                |              |
      |              |                    |                  +---------------->                |              |
      |              |                    |                  |                |                |              |
      |              |                    |                  | job enqueue    |                |              |
      |              |                    |                  +------------------------------------------------>
      |              |                    |                  |                |                |              |
      |              |                    | reply message    |                |                | job dequeue  |
      |              |                    <------------------+                |                |-------------->
      |              | send reply message |                  |                | obtain lock    |              |
      |              <--------------------+                  |                <----------------+              |
      | call return  |                    |                  |                |                |              |
      <--------------+                    |                  |                |        run job |              |
      |              |                    |                  |                |           +----+              |
      |              |                    |                  |                |           |    |              |
      |              |                    |                  |                |           |    |              |
      |              |                    |                  |                |           +---->              |
      |              |                    |                  |                |                |              |                                                                         |              |
      |              |                    |                  |                |                |              |
      +              +                    +                  +                +                +              +

In the above graph, **Loop Worker** is a new-introduced thread to do the actual
work. **Job Queue** is an eventlet queue [4]_ used to coordinate **Handle
Worker** who produces job entries and **Loop Worker** who consumes job entries.
While accessing an empty queue, **Loop Worker** will be blocked until some job
entries are put into the queue. **Loop Worker** retrieves job entries from the
job queue then start to run it. Similar to the original flow, since multiple
workers may get the same type of job for the same resource at the same time,
workers need to obtain the lock before it can run the job. One problem occurs
whenever XJob daemon stops before it finishes all the jobs in the job queue;
all unfinished jobs are lost. To solve it, we make changes to the original
periodical task that is used to redo failed job, and let it also handle the
jobs which have been registered for a certain time but haven't been started.
So both failed jobs and "orphan" new jobs can be picked up and redone.

You can see that **Handle Worker** doesn't do many works, it just consumes RPC
messages, register jobs then put job items in the job queue. So one extreme
solution here, will be to register new jobs in the API server side and start
worker threads to retrieve jobs from the database and run them. In this way, we
can remove all the RPC processes and use database to coordinate. The drawback
of this solution is that we don't dispatch jobs. All the workers query jobs
from the database so there is high probability that some of the workers obtain
the same job and thus race occurs. In the first solution, message broker
helps us to dispatch messages, and so dispatch jobs.

Considering job dispatch is important, we can make some changes to the second
solution and move to the third one, that is to also register new jobs in the
API server side, but we still use cast method to trigger asynchronous job in
XJob daemon. Since job registration is done in the API server side, we are not
afraid that the jobs will be lost if cast messages are lost. If API server side
fails to register the job, it will return response of failure; If registration
of job succeeds, the job will be done by XJob daemon at last. By using RPC, we
dispatch jobs with the help of message brokers. One thing which makes cast
method better than call method is that retrieving RPC messages and running job
handles are done in the same thread so if one XJob daemon is busy handling
jobs, RPC messages will not be dispatched to it. However when using call
method, RPC messages are retrieved by one thread(the **Handle Worker**) and job
handles are run by another thread(the **Loop Worker**), so XJob daemon may
accumulate many jobs in the queue and at the same time it's busy handling jobs.
This solution has the same problem with the call method solution. If cast
messages are lost, the new jobs are registered in the database but no XJob
daemon is aware of these new jobs. Same way to solve it, use periodical task to
pick up these "orphan" jobs. Here is the flow::

  +--------+     +--------+         +---------+     +---------------+   +----------+
  |        |     |        |         |         |     |               |   |          |
  | API    |     | RPC    |         | Message |     | RPC Server    |   | Database |
  | Server |     | client |         | Broker  |     | Handle Worker |   |          |
  |        |     |        |         |         |     |               |   |          |
  +---+----+     +---+----+         +----+----+     +-------+-------+   +----+-----+
      |              |                   |                  |                |
      | call RPC API |                   |                  |                |
      +-------------->                   |                  |                |
      |              | register job      |                  |                |
      |              +------------------------------------------------------->
      |              |                   |                  |                |
      |              | [if succeed to    |                  |                |
      |              |  register job]    |                  |                |
      |              | send cast message |                  |                |
      |              +------------------->                  |                |
      | call return  |                   | dispatch message |                |
      <--------------+                   +------------------>                |
      |              |                   |                  | obtain lock    |
      |              |                   |                  +---------------->
      |              |                   |                  |                |
      |              |                   |                  | run job        |
      |              |                   |                  +----+           |
      |              |                   |                  |    |           |
      |              |                   |                  |    |           |
      |              |                   |                  <----+           |
      |              |                   |                  |                |
      |              |                   |                  |                |
      +              +                   +                  +                +

Discussion
==========

In this section we discuss the pros and cons of the above three solutions.

.. list-table:: **Solution Comparison**
    :header-rows: 1

    * - Solution
      - Pros
      - Cons
    * - API server uses call
      - no RPC message lost
      - downtime of unfinished jobs in the job queue when XJob daemon stops,
        job dispatch not based on XJob daemon workload
    * - API server register jobs + no RPC
      - no requirement on RPC(message broker), no downtime
      - no job dispatch, conflict costs time
    * - API server register jobs + uses cast
      - job dispatch based on XJob daemon workload
      - downtime of lost jobs due to cast messages lost

Downtime means that after a job is dispatched to a worker, other workers need
to wait for a certain time to determine that job is expired and take over it.

Conclusion
==========

We decide to implement the third solution(API server register jobs + uses cast)
since it improves the asynchronous job reliability and at the mean time has
better work load dispatch.

Data Model Impact
=================

None

Dependencies
============

None

Documentation Impact
====================

None

References
==========

.. [1] https://docs.google.com/document/d/1zcxwl8xMEpxVCqLTce2-dUOtB-ObmzJTbV1uSQ6qTsY
.. [2] https://www.rabbitmq.com/tutorials/tutorial-two-python.html
.. [3] https://www.rabbitmq.com/confirms.html
.. [4] http://eventlet.net/doc/modules/queue.html
