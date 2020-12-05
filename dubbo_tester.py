import json
import telnetlib
from urllib.parse import unquote

from kazoo.client import KazooClient

# zookeeper的ip和端口
zk = {
	'host': '172.16.253.21',
	'port': 2181
}

class Zookeeper:
	client = None
	service_dict = {}

	class ServiceNotAvailableError(ValueError):
		pass


	def __init__(self, timeout=100):
		# 连接zookeeper
		self.client = KazooClient('%s:%s' % (zk['host'], zk['port']), timeout=timeout)
		self.client.start()

		# 查找所有注册的dubbo服务
		service_list = self.client.get_children('dubbo')
		for service in service_list:
			name = str(service).split('.')[-1]  # 去掉包名，剩下的服务名作为key
			self.service_dict[name] = service  # 此处如果有重名的服务，会覆盖


	def get_service_address(self, service):
		"""获取指定服务的注册地址信息"""
		if '.' not in service:
			# 如果传入的服务名不带包名，就从service_dict找到完成服务名
			service = self.service_dict[service]

		uri = 'dubbo/%s' % service
		if not self.client.exists(uri):
			raise ServiceNotAvailableError('服务"%s"不存在' % service)
		elif not self.client.exists('%s/providers' % uri):
			raise ServiceNotAvailableError('服务"%s"没有提供者' % service)
		else:
			providers = self.client.get_children('%s/providers' % uri)
			addrs = []
			for provider in providers:
				addr = str(unquote(provider)).split('/')[2]
				addrs.append((str(addr).split(':')[0], str(addr).split(':')[1], str(addr)))
			return addrs


	def close(self):
		self.client.stop()
		self.client.close()



class DubboTester(telnetlib.Telnet):
	class Args:

		def __init__(self, service, method, params, host=None, port=0, index=0):
			self.service = service
			self.method = method
			self.params = params
			self.host = host
			self.port = port
			self.index = index

	prompt = 'dubbo>'
	coding = 'utf-8'
	zk = Zookeeper()
	args = None

	def __init__(self, args: Args or dict):
		"""
		实例化DubboTester，这一步会连接到指定服务的服务器
		:param args: 可以穿Args对象实例，也可以穿字典数据，字典最少要包含service、method、params,
			params必须是list类型，list中的元素就是方法所需的参数
		"""
		# dict解析成Args对象
		if isinstance(args, dict):
			args = self.__init_args_from_dict(args) if isinstance(args, dict) else args
		address_list = self.zk.get_service_address(args.service)
		if len(address_list) > 1:
			# 对于多实例服务，默认连接第一个实例，可用index指定
			print('——' * 43)
			print('|%s服务有多个地址，使用index参数指定请求地址，默认index=0：|' % str(args.service).center(30, ' '))
			print('-' * 86)
			for i, address in enumerate(address_list):
				print('| %d ==> %s:%s |' % (i, address[0], str(address[1]).ljust(80 - len(address[2]), ' ')))
			print('——' * 43)

		args.host = address_list[args.index][0]
		args.port = address_list[args.index][1]
		print('当前连接地址： %s:%s' % (args.host, args.port))
		self.args = args
		super(DubboTester, self).__init__(host=args.host, port=args.port)
		self.write(b'\n')


	@staticmethod
	def __init_args_from_dict(d):
		service = d.get('service')
		method = d.get('method')
		params = d.get('params', [])
		host = d.get('host')
		port = d.get('port')
		index = d.get('index', 0)
		if port is not None and not isinstance(port, int):
			raise TypeError('port必须是数值类型')
		elif params is not None and not isinstance(params, list):
			raise TypeError('params必须是list类型')
		return DubboTester.Args(service, method, params, port, index)


	@staticmethod
	def __parse_args(args):
		"""将参数解析成tenlet命令行调用的字符串格式"""
		if isinstance(args, str) or isinstance(args, dict):
			args = json.dumps(args)
		elif isinstance(args, list):
			tmp = ''
			for arg in args:
				tmp += json.dumps(arg) + ','
			args = tmp[:-1]
		return args



	def command(self, flag, str_=""):
		data = self.read_until(flag.encode())
		self.write(str_.encode() + b'\n')
		return data


	def invoke(self):
		arg = self.__parse_args(self.args.params)
		command_str = "invoke {0}.{1}({2})".format(self.args.service, self.args.method, arg)
		print(self.prompt, command_str)
		self.command(self.prompt, command_str)
		data = self.command(self.prompt, "")
		# [:-6] 截取掉返回结果末尾的'dubbo>'
		data = data.decode(self.coding, errors='ignore')[:-6].strip()
		# 截取掉elapsed及之后的部分
		if 'elapsed' in data:
			data = data[:data.index('elapsed')].strip()
		# 双换行符替换为单换行符
		data = data.replace('\r\n', '\n')
		return data


	def close(self):
		if self.zk:
			self.zk.close()


def run(case: dict):
	try:
		tester = DubboTester(case)
		result = tester.invoke()
		try:
			# 解析结果，结果缩进，支持中文
			result = json.dumps(json.loads(result), ensure_ascii=False, sort_keys=True, indent=4)
		except json.JSONDecodeError as e:
			print(e)
		print('请求结果：\n%s ' % result)
		tester.close()
	except TimeoutError:
		print('连接超时！')


if __name__ == '__main__':
	case = {
		'service': 'UserInfoRpcService',
		'method': 'getUserState',
		'params': [600001]
	}
	run(case)
