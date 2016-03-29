import patcherex

import logging
from patcherex.patches import *
from patcherex.backends.basebackend import BaseBackend

l = logging.getLogger("patcherex.techniques.SimpleCFI")

class SimpleCFI(object):

    def __init__(self,binary_fname):
        self.binary_fname = binary_fname
        self.patcher = BaseBackend(self.binary_fname)

    def get_common_patches(self):
        common_patches = []

        # roughly in order of frequency. x86 encoding is just insane.
        # it assumes that eax points to the "after call" instruction
        added_code = '''
            cmp BYTE [eax-0x5], 0xE8 ; call 0x11223344
            je _exit    
            cmp BYTE [eax-0x6], 0xFF ; call [0x11223344]
            je _exit
            cmp BYTE [eax-0x2], 0xFF ; call eax
            je _exit
            cmp BYTE [eax-0x3], 0xFF ; call [eax+edx]
            je _exit
            cmp BYTE [eax-0x4], 0xFF ; call [eax+edx+0x1]
            je _exit
            cmp BYTE [eax-0x7], 0xFF ; call [eax*8+edx+0x11223344]
            je _exit
            cmp BYTE [eax-0x3], 0xE8 ; call 0x1122 (using 0x66 as prefix before E8)
            je _exit
            cmp BYTE [eax-0x5], 0xFF ; not sure if possible
            je _exit
            ; terminate(0x45)
            xor ebx, ebx
            mov bl, 0x45
            xor eax, eax
            inc eax
            int 0x80
            _exit:
            ret
        '''
        common_patches.append(AddCodePatch(added_code,name="simplecfi_test_int"))

        added_code = '''
            push eax
            mov eax, DWORD [esp+0x8]
            call {simplecfi_test_int}
            pop eax
            ret
        '''
        common_patches.append(AddCodePatch(added_code,name="simplecfi_test_no_offset"))

        return common_patches

    def add_simplecfi_test(self,end):
        #the idea is to keep this code as small as possible, since it will be injected in a lot of places
        added_code = '''
            call {simplecfi_test_no_offset}
        '''

        patch = InsertCodePatch(end,added_code,name="simplecfi_check_%08X"%end)
        return [patch]

    def function_to_ret_locations(self,ff):
        #TODO add more checks for validity
        if not ff.is_syscall and ff.returning and not ff.has_unresolved_calls and not ff.has_unresolved_jumps:
            start = ff.startpoint
            ends = set()
            for endpoint in ff.endpoints:
                bb = self.patcher.project.factory.block(endpoint)
                last_instruction = bb.capstone.insns[-1]
                if last_instruction.mnemonic != u"ret":
                    l.debug("bb at %s does not terminate with a ret in function %s" % (hex(int(bb.addr)),ff.name))
                    break
                else:
                    if last_instruction.op_str == "":
                        offset = 0
                    else:
                        offset = int(last_instruction.op_str,16)
                    ends.add((int(last_instruction.address),offset))
            else:
                if len(ends) == 0:
                    l.debug("cannot find any ret in function %s" % ff.name)
                else:
                    return ends #avoid "long" problems
            
        l.debug("function %s has problems and cannot be patched" % ff.name)
        return []

    def get_patches(self):
        common_patches = self.get_common_patches()

        patches = []
        cfg = self.patcher.cfg
        for k,ff in cfg.function_manager.functions.iteritems():
            ends = self.function_to_ret_locations(ff)
            for end,offset in ends:
                #I realize that we do not really care about the offset in the "ret imm16" case
                new_patch = self.add_simplecfi_test(end)
                l.info("added simplecfi patch to function %s, ret %s, offset %s",ff.name,hex(end),hex(offset))
                patches += new_patch

        return common_patches + patches