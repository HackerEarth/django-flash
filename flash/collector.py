import six

from collections import defaultdict
from functools import wraps

from .lazy_utils import Lazy, LazyCall, eval_object


ltype = (list, tuple)
Identity = object()

def smallest_path(iterable):
    min_cost = None
    min_path = None
    for path, cost in iterable:
        if min_path is None or min_path > cost:
            min_path = path
            min_cost = cost
    return min_path, min_cost

class LazyCollectorMeta(type):
    def __init__(self, *args, **kwargs):
        super(LazyCollectorMeta, self).__init__(*args, **kwargs)

        if self.__name__ == 'LazyCollector':
            return

        self.check_params_list()
        self.check_collectables()
        self.check_collector()

        self.store_connections()
        self.insure_collectables_achievable()

    def check_params_list(self):
        assert hasattr(self, 'params_list')
        params_list = self.params_list
        assert isinstance(params_list, ltype)
        for params in params_list:
            assert isinstance(params, ltype)

    def check_collectables(self):
        assert hasattr(self, 'collectables')
        for node in self.collectables:
            assert isinstance(node, basestring)

    def check_collector(self):
        assert hasattr(self, 'collector')
        assert isinstance(self.collector, dict)
        for key, value in self.collector.items():
            assert isinstance(key, basestring)
            assert isinstance(value, ltype)
            for v in value:
                assert isinstance(v, basestring)
                assert v in self.collectables

    def store_connections(self):
        self.connections = defaultdict(list)
        for value in self.__dict__.itervalues():
            if hasattr(value, 'connect_params'):
                self.register_connect(value)

    def register_connect(self, func):
        connect_params = func.connect_params
        connect_params['func'] = func
        to_node = connect_params['to_node']
        self.connections[to_node].append(connect_params)

    def insure_collectables_achievable(self):
        self.paths = {}
        for end_node in self.collectables:
            for params in self.params_list:
                path, _cost = smallest_path(self.get_path(end_node, params))
                assert path is not None, (
                        "No path exists from %s to %s" % (params, end_node))
                self.paths[(end_node, params)] = path

    def get_path(self, end_node, params, node_visited=None):
        for param in params:
            if param == end_node:
                yield Identity, 0

        if node_visited is None:
            node_visited = set()
        else:
            node_visited = set(node_visited)
        node_visited.add(end_node)

        for connection in self.connections[end_node]:
            paths_list = []
            exists = True
            cost_sum = int(connection['cache_hit'] == True)
            for from_node in connection['from_nodes']:
                if from_node in node_visited:
                    exists = False
                    break
                path, cost = smallest_path(self.get_path(from_node, params,
                        node_visited=node_visited))
                if path is None:
                    exists = False
                    break
                paths_list.append(path)
                cost_sum += cost
            if exists:
                yield (connection, paths_list), cost_sum

    def get(self, collector_name, **kwargs):
        return eval_object(self.get_lazy(collector_name, **kwargs))

    def get_lazy(self, collector_name, **kwargs):
        params = tuple(sorted(kwargs.keys()))
        assert params in self.params_list
        d = {}
        for end_node in self.collector[collector_name]:
            d[end_node] = self.get_node(end_node, params, kwargs)
        return Lazy(d)

    def get_node(self, end_node, params, kwargs):
        if isinstance(end_node, basestring):
            path = self.paths[(end_node, params)]
        else:
            path = end_node
            end_node = path[0]['to_node']
        if path is Identity:
            return kwargs[end_node]
        func = path[0]['func']
        rest = path[1]
        args = []
        from_nodes = list(path[0]['from_nodes'])
        from_nodes_orig = path[0]['from_nodes_orig']
        for node in from_nodes_orig:
            index = from_nodes.index(node)
            node_path = rest[index]
            if node_path is Identity:
                args.append(kwargs[node])
            else:
                args.append(Lazy(self.get_node(node_path, params, kwargs)))
        return LazyCall(func, self, *args)


class LazyCollector(six.with_metaclass(LazyCollectorMeta, object)):
    pass

def connect(from_nodes, to_node, cache_hit=False):
    if not isinstance(from_nodes, ltype):
        from_nodes = (from_nodes,)
    from_nodes_orig = from_nodes
    from_nodes = tuple(sorted(from_nodes))
    for val in from_nodes:
        assert isinstance(val, basestring)
    assert isinstance(to_node, basestring)

    def decorator(method):
        method.connect_params = {
            'from_nodes': from_nodes,
            'from_nodes_orig': from_nodes_orig,
            'to_node': to_node,
            'cache_hit': cache_hit
        }
        @wraps(method)
        def wrapped_method(*args, **kwargs):
            result = method(*args, **kwargs)
            if cache_hit:
                return Lazy(result)
            return result
        return wrapped_method
    return decorator
