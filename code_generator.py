import os, re
from constants import *

class CodeGenerator():
    def __init__(self, src_path) -> None:
        self.src_path = src_path
        self.excluded = ["doc.go", "openapi_generated.go", "zz_generated.deepcopy.go"]
    
    def scan_code(self):
        """ scan struct and type definitions in codes
        """        
        # struct objects
        objects = {}
        # type_def: type xxx string
        type_def = {}

        for path in self.src_path:
            for file in os.listdir(path):
                if file in self.excluded or "_conversion" in file:
                    continue
                file = os.path.join(path, file)
                with open(file, 'r') as f:
                    file = f.readlines()
                # preproc
                file = self.remove_comment(file)

                for p in range(len(file)):
                    line = file[p]
                    if RE_STRUCT.findall(line):
                        obj_name = RE_STRUCT.findall(line)[0]
                        fields, p = self.get_struct(file, p)
                        objects[obj_name] = fields
                    elif line[: 4] == "type":
                        line = line.split()
                        assert len(line) == 3
                        type_def[line[1]] = line[2]
        self.objects = objects
        self.type_def = type_def
        self.check_dfs()

    def check_dfs(self):
        objects = self.objects
        type_def = self.type_def
        for k, v in objects.items():
            for k1, v1 in v.items():
                v_type = v1['type'].replace("[]", "").replace("*", "")
                v1["need_dfs"] = False
                v1["is_type_def"] = False
                v1['is_map'] = False
                if v_type in objects:
                    v1["need_dfs"] = True
                elif v_type in type_def:
                    tmp = type_def[v_type].replace("[]", "").replace("*", "")
                    if tmp in objects:
                        v[k1]['type'] = type_def[v_type]
                        if "[]" in type_def[v_type]:
                            v1["is_list"] = True
                        if "*" in type_def[v_type]:
                            v1['is_ptr'] = True
                        v1["need_dfs"] = True
                    else:
                        v1["is_type_def"] = True
                elif RE_MAP.findall(v_type):
                    v1['is_map'] = True
                    assert RE_MAP.findall(v_type)[0][0] not in objects
                    if RE_MAP.findall(v_type)[0][1] in objects:
                        v1["need_dfs"] = True

    
    def deep_gen(self, objects, name, dst, dst_field, src, src_field, version):
        lines = []
        fields = objects[name.replace("*", "").replace("[]", "")]
        for k, v in fields.items():
            if k == "TypeMeta":
                continue
            if v['is_list'] and v['need_dfs']:
                array = k
                array = array[0].lower() + array[1: ]
                v_type = v['type'].replace("[]", "").replace("*", "")
                for_val = "%s_val"%array
                for_idx = "%s_idx"%array
                if src_field:
                    in_val = f"{src}.{src_field}.{k}".strip(".")
                else:
                    in_val = f"{src}.{k}".strip(".")
                type_prefix = f"{version}.{v_type}".strip(".")
                array_def = f"{array} := make([]{type_prefix}, len({in_val}))"
                for_start = f"for {for_idx}, {for_val} := range {in_val} " + "{"
                lines.append(array_def)
                lines.append(for_start)
                tmp = self.deep_gen(objects, v['type'], f"{array}[{for_idx}]", "", for_val, "", version)
                lines.extend(tmp)
                lines.append("}")
                if dst_field:
                    assign_val = f"{dst}.{dst_field}.{k}".strip(".")
                else:
                    assign_val = f"{dst}.{k}".strip(".")
                lines.append(f"{assign_val} = {array}")
            elif v['is_map'] and v['need_dfs']:
                obj_map = k
                obj_map = obj_map[0].lower() + obj_map[1: ]
                for_val = "%s_val"%obj_map
                for_key = "%s_key"%obj_map
                if src_field:
                    in_val = f"{src}.{src_field}.{k}".strip(".")
                else:
                    in_val = f"{src}.{k}".strip(".")
                assign = RE_MAP.findall(v['type'])[0]
                map_type = f"{version}.{assign}".strip(".")
                map_type = v['type'].replace(assign, map_type)
                map_def = f"{obj_map} := make({map_type}, len({in_val}))"
                for_start = f"for {for_key}, {for_val} := range {in_val} " + "{"
                
                assign_val = assign
                assign = assign[0].lower() + assign[1: ]
                assign_val = f"{version}.{assign_val}".strip(".")
                assign_line = f"{assign} := {assign_val}{{}}"
                lines.append(map_def)
                lines.append(for_start)
                lines.append(assign_line)
                tmp = self.deep_gen(objects, RE_MAP.findall(v['type'])[0], assign, "", for_val, "", version)
                lines.extend(tmp)
                lines.append(f"{obj_map}[{for_key}] = {assign}")
                lines.append("}")
                assign = f"{dst}.{dst_field}.{k}".replace("..", ".")
                lines.append(f"{assign} = {obj_map}")
            elif v['need_dfs']:                    
                tmp = self.deep_gen(objects, v['type'], dst, f"{dst_field}.{k}".strip("."), src, f"{src_field}.{k}".strip("."), version)
                if v['is_ptr']:
                    cur_src_field = f"{src_field}.{k}".strip(".")
                    lines.append(f"if {src}.{cur_src_field} != nil " + "{")

                    assign = f"{dst_field}.{k}".strip(".")
                    assign_val = f"{version}.{v['type'].replace('*', '')}{{}}".strip(".")
                    assign = f"{dst}.{assign} = &{assign_val}"
                    lines.append(assign)
                    lines.extend(tmp)
                    lines.append("}")
                else:
                    lines.extend(tmp)
            else:
                cur_dst_field = f"{dst_field}.{k}".strip(".")
                cur_src_field = f"{src_field}.{k}".strip(".")
                if v['is_type_def']:
                    v_type = v['type'].replace("[]", "").replace("*", "")
                    type_prefix = f"{version}.{v_type}".strip(".")
                    line = f"{dst}.{cur_dst_field} = {type_prefix}({src}.{cur_src_field})"
                else:
                    line = f"{dst}.{cur_dst_field} = {src}.{cur_src_field}"
                lines.append(line)
        return lines
    
    def remove_comment(self, file):
        tmp = []
        comment = False
        for line in file:
            if "/*" in line:
                comment = True
                continue
            if "*/" in line:
                comment = False
                continue
            if "//" in line:
                continue
            if comment:
                continue
            if not line.strip():
                continue
            tmp.append(line)
        return tmp

    def get_struct(self, file, p):
        fields = {}
        p += 1
        pattern = r'`[^`]*`'
        for i in range(p, len(file)):
            line = file[i]
            if line.strip() == "}":
                return fields, i
            line = re.sub(pattern, "", line).strip()
            field = line.split()
            if len(field) == 2:
                field_name, field_type = field
            elif len(field) == 1:
                field_type = field[0]
                field_name = field_type.split(".")[-1]
            else:
                raise Exception("unexpected input: %s"%line)
            is_list = False
            is_ptr = False
            if "[]" in field_type:
                is_list = True
            if "*" in field_type:
                is_ptr = True
            fields[field_name] = {"type": field_type, "is_list": is_list, "is_ptr": is_ptr}