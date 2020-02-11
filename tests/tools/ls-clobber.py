#!/usr/bin/python
from threading import Thread
import time
import socket
from contextlib import closing
from Queue import Queue

def receive_data(s, size):
	"""
	Receive (recv()) <size> bytes from socket <s>.
	"""
	result = ''
	while size > 0:
		packet = s.recv(size)
		if len(packet) == 0:
			raise Exception("livestatus closed connection")
		size -= len(packet)
		result += packet
	return result

def receive_response(s):
	"""
	Receive a livestatus response in fixed16 format.

	The fixed16 response header has the following format:

    Bytes 1-3: status code
    Byte 4: a single space
    Byte 5-15: the length of the response as an ASCII coded integer number, padded with spaces
    Byte 16: a linefeed character (ASCII 10)
	"""
	resp = receive_data(s, 16)
	length = int(resp[4:].lstrip())

	data = receive_data(s, length)
	return data

def run_query(q, query='', unix_socket=None, tcp_port=None, idle_time_s=0):
	if not query.endswith('\n'):
		query.append('\n')
	start_t = time.time()
	with closing(socket.socket(
			socket.AF_UNIX if unix_socket else socket.AF_INET,
			socket.SOCK_STREAM)) as s:
		s.connect(unix_socket or ('localhost', tcp_port))
		s.send(query)
		s.send('KeepAlive: on\n')
		#fixed16 so that we can read the entire message without relying on
		# socket close
		s.send('ResponseHeader: fixed16\n\n')
		# Receive response from Livestatus, although the response data is not used here.
		receive_response(s)
		time.sleep(idle_time_s)
	end_t = time.time()
	q.put(end_t - start_t)

def clobber(q, unix_socket=None, tcp_port=None, num_threads=1, idle_time=1, query='GET services\n'):
	threads = []
	start_t = time.time()
	for _ in range(num_threads):
		th_args = {
			'idle_time_s': idle_time,
			'unix_socket': unix_socket,
			'tcp_port': tcp_port,
			'query': query
			}
		threads.append(
				Thread(target=run_query, args=[q], kwargs=th_args)
				)
		threads[-1].start()

	for t in threads:
		t.join()

	end_t = time.time()
	return end_t - start_t

def main():
	import argparse
	from os import path
	import json
	def existing_path(string):
		if not path.exists(string):
			msg = 'no socket at %s' % string
			raise argparse.ArgumentTypeError(msg)

		return string

	parser = argparse.ArgumentParser(description='Clobber Livestatus with concurrent queries for benchmarking.')
	parser.add_argument('nthreads', type=int, help='the number of concurrent threads to spawn - one thread = one query')
	parser.add_argument('idle_time', type=int, help='the time (in seconds) that a thread keeps its socket open before terminating')
	parser_socket = parser.add_mutually_exclusive_group(required=True)
	parser_socket.add_argument('--unix-socket', type=existing_path, help='path to the Livestatus UNIX socket')
	parser_socket.add_argument('--tcp-port', type=int, help='TCP port for inet socket')
	args = parser.parse_args()
	q = Queue()
	total_time = clobber(
		q,
		unix_socket=args.unix_socket,
		tcp_port=args.tcp_port,
		num_threads=args.nthreads,
		idle_time=args.idle_time)

	results = []
	while not q.empty():
		results.append(q.get())

	max_time = max(results)
	min_time = min(results)
	avg_time = reduce(lambda x, y: x+y, results) / len(results)

	print(json.dumps({
				'total_time': total_time,
				'max_time': max_time,
				'min_time': min_time,
				'avg_time': avg_time
				}))


if __name__ == '__main__':
	main()
