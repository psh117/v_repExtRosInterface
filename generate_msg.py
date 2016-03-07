from sys import argv, exit, stderr
import re

# used to resolve messages specified without a package name
# name -> pkg/name
resolve_msg = {}

def is_identifier(s):
    return re.match('^[a-zA-Z_][a-zA-Z0-9_]*$', s)

# parse a type specification, such as Header, geometry_msgs/Point, or string[12]
class TypeSpec:
    def __init__(self, s):
        self.array = False
        self.array_size = None
        m = re.match(r'^(.*)\[(\d*)\]$', s)
        if m:
            self.array = True
            s = m.group(1)
            if len(m.group(2)) > 0:
                self.array_size = int(m.group(2))
        # perform substitutions:
        if s in resolve_msg: s = resolve_msg[s]
        if s == 'byte': s = 'int8' # deprecated
        if s == 'char': s = 'uint8' # deprecated
        # check builtins:
        self.builtin = s in ('bool', 'int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64', 'float32', 'float64', 'string', 'time', 'duration')
        self.fullname = s
        if self.builtin:
            self.mtype = s
        else:
            if '/' not in s:
                raise ValueError('bad type: %s' % s)
            tok = s.split('/')
            if len(tok) != 2:
                raise ValueError('bad type: %s' % s)
            if not is_identifier(tok[0]) or not is_identifier(tok[1]):
                raise ValueError('bad type: %s' % s)
            self.package = tok[0]
            self.mtype = tok[1]

    # normalize fullname to C identifier (replace / with __)
    def normalized(self):
        return ('{}__'.format(self.package) if not self.builtin else '') + self.mtype

    # get C++ type declaration
    def ctype(self):
        if self.builtin:
            if self.mtype == 'bool': return 'uint8_t'
            if self.mtype == 'int8': return 'int8_t'
            if self.mtype == 'uint8': return 'uint8_t'
            if self.mtype == 'int16': return 'int16_t'
            if self.mtype == 'uint16': return 'uint16_t'
            if self.mtype == 'int32': return 'int32_t'
            if self.mtype == 'uint32': return 'uint32_t'
            if self.mtype == 'int64': return 'int64_t'
            if self.mtype == 'uint64': return 'uint64_t'
            if self.mtype == 'float32': return 'float'
            if self.mtype == 'float64': return 'double'
            if self.mtype == 'string': return 'std::string'
            if self.mtype == 'time': return 'ros::Time'
            if self.mtype == 'duration': return 'ros::Duration'
            raise Exception('can\'t get ctype of builtin %s' % self.mtype)
        return self.package + '::' + self.mtype

    def __str__(self):
        t = self.mtype
        if not self.builtin:
            t = self.package + '/' + t
        if self.array:
            t += '[]'
        return t

fields = {}

if len(argv) != 5 or argv[1] not in ('cpp', 'h', 'adv', 'pub', 'sub'):
    stderr.write('argument error\n')
    exit(42)

mode = argv[1]
filename = argv[2]
gt = TypeSpec(argv[3])

# populate resolve_msg dictionary
with open(argv[4]) as f:
    for l in f.readlines():
        l = l.strip()
        pkg, n = l.split('/')
        resolve_msg[n] = l

# parse message definition
with open(filename) as f:
    for ln_orig in f.readlines():
        ln = ln_orig.strip()

        if '#' in ln:
            # strip comments
            ln = ln[:ln.find('#')].strip()

        if ln == '':
            # ignore empty lines
            continue

        ln_orig1 = ln

        ln = ln.replace('=',' = ')

        tokens = ln.split()

        if len(tokens) == 4 and tokens[2] == '=':
            # it's a constant definition: ignore
            continue

        if len(tokens) == 2:
            t = TypeSpec(tokens[0])
            n = tokens[1]
            fields[n] = t
        else:
            print('error: unrecognized line:')
            print(ln_orig1)
            exit(3)


wfn = 'write__' + gt.normalized()
wfn_sig = 'bool {wfn}(const {ctype_}& msg, int stack)'.format(ctype_=gt.ctype(), **locals())

if mode == 'h':
    print('%s;' % wfn_sig)

if mode == 'cpp':
    wf = '''
{wfn_sig}
{{
    if(simPushTableOntoStack(stack) == -1)
    {{
        std::cerr << "{wfn}" << ": " << "error: " << "push table failed." << std::endl;
        return false;
    }}'''.format(ctype_=gt.ctype(), **locals())
    for n, t in fields.items():
        if t.array:
            wf += '''
    if(simPushStringOntoStack(stack, "{n}", 0) == -1)
    {{
        std::cerr << "{wfn}" << ": " << "error: " << "push table key (" << "{nf}" << ") failed." << std::endl;
        return false;
    }}
    if(simPushTableOntoStack(stack) == -1)
    {{
        std::cerr << "{wfn}" << ": " << "error: " << "push array table (" << "{nf}" << ") failed." << std::endl;
        return false;
    }}
    for(int i = 0; i < msg.{n}.size(); i++)
    {{
        if(!write__int32(i + 1, stack))
        {{
            std::cerr << "{wfn}" << ": " << "error: " << "push array table key " << i << " (" << "{nf}" << ") failed." << std::endl;
            return false;
        }}
        if(!write__{norm}(msg.{n}[i], stack))
        {{
            std::cerr << "{wfn}" << ": " << "error: " << "push array table value (" << "{nf}" << ") failed." << std::endl;
            return false;
        }}
        if(simInsertDataIntoStackTable(stack) == -1)
        {{
            std::cerr << "{wfn}" << ": " << "error: " << "insert array table pair (" << "{nf}" << ") failed." << std::endl;
            return false;
        }}
    }}
    if(simInsertDataIntoStackTable(stack) == -1)
    {{
        std::cerr << "{wfn}" << ": " << "error: " << "insert table pair (" << "{nf}" << ") failed." << std::endl;
        return false;
    }}
'''.format(norm=t.normalized(), nf='{}::{}'.format(gt.ctype(), n), **locals())
        else:
            wf += '''
    if(simPushStringOntoStack(stack, "{n}", 0) == -1)
    {{
        std::cerr << "{wfn}" << ": " << "error: " << "push table key (" << "{nf}" << ") failed." << std::endl;
        return false;
    }}
    if(!write__{norm}(msg.{n}, stack))
    {{
        std::cerr << "{wfn}" << ": " << "error: " << "push table field " << "{nf}" << " of type " << "{t}" << " failed." << std::endl;
        return false;
    }}
    if(simInsertDataIntoStackTable(stack) == -1)
    {{
        std::cerr << "{wfn}" << ": " << "error: " << "insert table pair " << "{nf}" << " failed." << std::endl;
        return false;
    }}'''.format(norm=t.normalized(), nf='{}::{}'.format(gt.ctype(), n), **locals())
    wf += '''
    return true;
}}

'''.format(**locals())
    print(wf)

rfn = 'read__' + gt.normalized()
rfn_sig = 'bool {rfn}(int stack, {ctype_} *msg)'.format(ctype_=gt.ctype(), **locals())

if mode == 'h':
    print('%s;' % rfn_sig)

if mode == 'cpp':
    rf = '''
bool {rfn}(int stack, {ctype_} *msg)
{{
    int i;
    if((i = simGetStackTableInfo(stack, 0)) != sim_stack_table_map)
    {{
        std::cerr << "{rfn}" << ": " << "error: " << "expected a table (simGetStackTableInfo returned " << i << ")." << std::endl;
        return false;
    }}

    int sz = simGetStackSize(stack);
    simUnfoldStackTable(stack);
    int numItems = (simGetStackSize(stack) - sz + 1) / 2;

    char *str;
    int strSz;

    while(numItems >= 1)
    {{
        simMoveStackItemToTop(stack, simGetStackSize(stack) - 2); // move key to top
        if((str = simGetStackStringValue(stack, &strSz)) != NULL && strSz > 0)
        {{
            simPopStackItem(stack, 1); // now stack top is value

            if(0) {{}}'''.format(ctype_=gt.ctype(), **locals())
    for n, t in fields.items():
        if t.array:
            if t.array_size:
                ins = 'msg->{n}[i] = (v);'.format(**locals())
            else:
                ins = 'msg->{n}.push_back(v);'.format(**locals())
            rf += '''
            else if(strcmp(str, "{n}") == 0)
            {{
                int i;
                if((i = simGetStackTableInfo(stack, 0)) < 0)
                {{
                    std::cerr << "{rfn}" << ": " << "error: " << "expected a array-table (simGetStackTableInfo returned " << i << ")." << std::endl;
                    return false;
                }}
                int sz1 = simGetStackSize(stack);
                simUnfoldStackTable(stack);
                int numItems = (simGetStackSize(stack) - sz + 1) / 2;
                for(int i = 0; i < numItems; i++)
                {{
                    simMoveStackItemToTop(stack, simGetStackSize(stack) - 2); // move key to top
                    int j;
                    if(!read__int32(stack, &j))
                    {{
                        std::cerr << "{rfn}" << ": " << "error: " << "not array table (" << str << ")." << std::endl;
                        return false;
                    }}
                    simPopStackItem(stack, 1); // now stack top is value
                    {ctype_} v;
                    if(!read__{norm}(stack, &v))
                    {{
                        std::cerr << "{rfn}" << ": " << "error: " << "value is not " << "{t}" << " for key: " << str << "." << std::endl;
                        return false;
                    }}
                    {ins}
                    simPopStackItem(stack, 1);
                }}
            }}'''.format(norm=t.normalized(), ctype_=t.ctype(), **locals())
        else:
            rf += '''
            else if(strcmp(str, "{n}") == 0)
            {{
                if(!read__{norm}(stack, &(msg->{n})))
                {{
                    std::cerr << "{rfn}" << ": " << "error: " << "value is not " << "{t}" << " for key: " << str << "." << std::endl;
                    return false;
                }}
            }}'''.format(norm=t.normalized(), **locals())
    rf += '''
            else
            {{
                std::cerr << "{rfn}" << ": " << "error: " << "unexpected key: " << str << "." << std::endl;
                return false;
            }}

            simReleaseBuffer(str);
        }}
        else
        {{
            std::cerr << "{rfn}" << ": " << "error: " << "malformed table (bad key type)." << std::endl;
            return false;
        }}

        numItems = (simGetStackSize(stack) - sz + 1) / 2;
    }}
    
    return true;
}}

'''.format(**locals())
    print(rf)

cb_sig = 'void ros_callback__{norm}(const boost::shared_ptr<{ctype_} const>& msg, SubscriberProxy *proxy)'.format(norm=gt.normalized(), ctype_=gt.ctype(), **locals())

if mode == 'h':
    print('%s;' % cb_sig)

if mode == 'cpp':
    cb = '''
{cb_sig}
{{
    int stack = simCreateStack();
    if(stack != -1)
    {{
        do
        {{
            if(!write__{norm}(*msg, stack))
            {{
                break;
            }}
            if(simCallScriptFunctionEx(proxy->topicCallback.scriptId, proxy->topicCallback.name.c_str(), stack) == -1)
            {{
                std::cerr << "ros_callback__{norm}" << ": " << "error: " << "call script failed." << std::endl;
                break;
            }}
        }}
        while(0);
        simReleaseStack(stack);
    }}
}}

'''.format(norm=gt.normalized(), ctype_=gt.ctype(), **locals())
    print(cb)

if mode == 'pub':
    p = '''    else if(publisherProxy->topicType == "{fn}")
    {{
        {ctype_} msg;
        if(!read__{norm}(p->stackID, &msg))
        {{
            simSetLastError("simExtROS_publish", "invalid message format (check stderr)");
            return;
        }}
        publisherProxy->publisher.publish(msg);
    }}'''.format(fn=gt.fullname, norm=gt.normalized(), ctype_=gt.ctype(), **locals())
    print(p)

if mode == 'adv':
    p = '''    else if(topicType == "{fn}")
    {{
        publisherProxy->publisher = nh->advertise<{ctype_}>(topicName, queueSize, latch);
    }}'''.format(fn=gt.fullname, norm=gt.normalized(), ctype_=gt.ctype(), **locals())
    print(p)

if mode == 'sub':
    p = '''    else if(topicType == "{fn}")
    {{
        subscriberProxy->subscriber = nh->subscribe<{ctype_}>(topicName, queueSize, boost::bind(ros_callback__{norm}, _1, subscriberProxy));
    }}'''.format(fn=gt.fullname, norm=gt.normalized(), ctype_=gt.ctype(), **locals())
    print(p)
