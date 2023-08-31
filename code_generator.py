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
        self.check_type()

    def check_type(self):
        for _, struct in self.objects.items():
            for _, attr in struct.items():
                field_type = attr['type']
                self.check_dfs(field_type, attr)
                self.check_map(field_type, attr)
                self.check_list(field_type, attr)
                self.check_ptr(field_type, attr)
                self.check_type_def(field_type, attr)

    def check_list(self, field_type, attr):
        attr['is_list'] = False
        if "[]" in field_type:
            attr['is_list'] = True
    
    def check_ptr(self, field_type, attr):
        attr['is_ptr'] = False
        if "*" in field_type:
            attr['is_ptr'] = True

    def check_map(self, field_type, attr):
        attr['is_map'] = False
        if RE_MAP.findall(field_type):
            attr['is_map'] = True
            # assert the key of map is not a custom type, since not supported currently
            assert RE_MAP.findall(field_type)[0][0] not in self.objects
            if RE_MAP.findall(field_type)[0][1] in self.objects:
                attr["need_dfs"] = True
    
    def check_type_def(self, field_type, attr):
        attr["is_type_def"] = False
        if field_type in self.type_def:
            tmp = self.type_def[field_type].replace("[]", "").replace("*", "")
            if tmp in self.objects:
                attr['type'] = self.type_def[field_type]
                self.check_list(self.type_def[field_type], attr)
                self.check_ptr(self.type_def[field_type], attr)
                attr["need_dfs"] = True
            else:
                attr["is_type_def"] = True

    def check_dfs(self, field_type, attr):
        field_type = attr['type'].replace("[]", "").replace("*", "")
        attr["need_dfs"] = False
        if field_type in self.objects:
            attr["need_dfs"] = True
    
    def deep_gen(self, objects, name, dst, dst_field, src, src_field, version):
        lines = []
        fields = objects[name.replace("*", "").replace("[]", "")]
        for filed_name, field_attr in fields.items():
            if filed_name == "TypeMeta":
                continue
            if field_attr['is_list'] and field_attr['need_dfs']:
                array = filed_name
                array = array[0].lower() + array[1: ]
                v_type = field_attr['type'].replace("[]", "").replace("*", "")
                for_val = "%s_val"%array
                for_idx = "%s_idx"%array
                if src_field:
                    in_val = f"{src}.{src_field}.{filed_name}".strip(".")
                else:
                    in_val = f"{src}.{filed_name}".strip(".")
                type_prefix = f"{version}.{v_type}".strip(".")
                array_def = f"{array} := make([]{type_prefix}, len({in_val}))"
                for_start = f"for {for_idx}, {for_val} := range {in_val} " + "{"
                lines.append(array_def)
                lines.append(for_start)
                tmp = self.deep_gen(objects, field_attr['type'], f"{array}[{for_idx}]", "", for_val, "", version)
                lines.extend(tmp)
                lines.append("}")
                if dst_field:
                    assign_val = f"{dst}.{dst_field}.{filed_name}".strip(".")
                else:
                    assign_val = f"{dst}.{filed_name}".strip(".")
                lines.append(f"{assign_val} = {array}")
            elif field_attr['is_map'] and field_attr['need_dfs']:
                obj_map = filed_name
                obj_map = obj_map[0].lower() + obj_map[1: ]
                for_val = "%s_val"%obj_map
                for_key = "%s_key"%obj_map
                if src_field:
                    in_val = f"{src}.{src_field}.{filed_name}".strip(".")
                else:
                    in_val = f"{src}.{filed_name}".strip(".")
                assign = RE_MAP.findall(field_attr['type'])[0][1]
                map_type = f"{version}.{assign}".strip(".")
                map_type = field_attr['type'].replace(assign, map_type)
                map_def = f"{obj_map} := make({map_type}, len({in_val}))"
                for_start = f"for {for_key}, {for_val} := range {in_val} " + "{"
                
                assign_val = assign
                assign = assign[0].lower() + assign[1: ]
                assign_val = f"{version}.{assign_val}".strip(".")
                assign_line = f"{assign} := {assign_val}{{}}"
                lines.append(map_def)
                lines.append(for_start)
                lines.append(assign_line)
                tmp = self.deep_gen(objects, RE_MAP.findall(field_attr['type'])[0][1], assign, "", for_val, "", version)
                lines.extend(tmp)
                lines.append(f"{obj_map}[{for_key}] = {assign}")
                lines.append("}")
                assign = f"{dst}.{dst_field}.{filed_name}".replace("..", ".")
                lines.append(f"{assign} = {obj_map}")
            elif field_attr['need_dfs']:                    
                tmp = self.deep_gen(objects, field_attr['type'], dst, f"{dst_field}.{filed_name}".strip("."), src, f"{src_field}.{filed_name}".strip("."), version)
                if field_attr['is_ptr']:
                    cur_src_field = f"{src_field}.{filed_name}".strip(".")
                    lines.append(f"if {src}.{cur_src_field} != nil " + "{")

                    assign = f"{dst_field}.{filed_name}".strip(".")
                    assign_val = f"{version}.{field_attr['type'].replace('*', '')}{{}}".strip(".")
                    assign = f"{dst}.{assign} = &{assign_val}"
                    lines.append(assign)
                    lines.extend(tmp)
                    lines.append("}")
                else:
                    lines.extend(tmp)
            else:
                cur_dst_field = f"{dst_field}.{filed_name}".strip(".")
                cur_src_field = f"{src_field}.{filed_name}".strip(".")
                if field_attr['is_type_def']:
                    v_type = field_attr['type'].replace("[]", "").replace("*", "")
                    type_prefix = f"{version}.{v_type}".strip(".")
                    line = f"{dst}.{cur_dst_field} = {type_prefix}({src}.{cur_src_field})"
                else:
                    line = f"{dst}.{cur_dst_field} = {src}.{cur_src_field}"
                lines.append(line)
        return lines
    
    def remove_comment(self, lines):
        """remove comments and blank lines

        Args:
            lines (list): lines of a file

        Returns:
            list: processed lines
        """        
        tmp = []
        comment = False
        for line in lines:
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
            fields[field_name] = {"type": field_type}