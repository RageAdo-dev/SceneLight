"""Optional OpenCL/GL sharing for Windows drivers with unusable GL compute.

No Python extension or pixel transfer is required. Every shared object belongs
to the GL device; its CL reference is released before resizing or closing it.
This module also runs unchanged in Ren'Py's Python 2 runtime.
"""

from __future__ import division

import contextlib
import ctypes as C
import weakref


class Unavailable(RuntimeError):
    pass


def checked(code):
    if code:
        raise Unavailable("OpenCL operation failed (%d)" % code)


class Backend(object):
    def __init__(self, device, profiling=False):
        self.device = weakref.proxy(device)
        self.images, self.buffers, self.programs, self.kernels = {}, {}, {}, {}
        self.context = self.queue = None
        self.profiling = profiling
        self.events, self.timings = [], []
        self.library = C.WinDLL("OpenCL.dll")
        p, u, n, i = C.c_void_p, C.c_uint, C.c_size_t, C.c_int
        pointer = C.POINTER
        signatures = {
            "GetPlatformIDs": (i, [u, pointer(p), pointer(u)]),
            "GetExtensionFunctionAddressForPlatform": (p, [p, C.c_char_p]),
            "GetDeviceInfo": (i, [p, u, n, p, pointer(n)]),
            "CreateContext": (p, [pointer(C.c_ssize_t), u, pointer(p), p, p, pointer(i)]),
            "CreateCommandQueue": (p, [p, p, C.c_ulonglong, pointer(i)]),
            "CreateProgramWithSource": (p, [p, u, pointer(C.c_char_p), pointer(n), pointer(i)]),
            "BuildProgram": (i, [p, u, pointer(p), C.c_char_p, p, p]),
            "GetProgramBuildInfo": (i, [p, p, u, n, p, pointer(n)]),
            "CreateKernel": (p, [p, C.c_char_p, pointer(i)]),
            "CreateBuffer": (p, [p, C.c_ulonglong, n, p, pointer(i)]),
            "CreateFromGLTexture": (p, [p, C.c_ulonglong, u, i, u, pointer(i)]),
            "EnqueueAcquireGLObjects": (i, [p, u, pointer(p), u, p, p]),
            "EnqueueReleaseGLObjects": (i, [p, u, pointer(p), u, p, p]),
            "SetKernelArg": (i, [p, u, n, p]),
            "EnqueueNDRangeKernel": (i, [p, p, u, p, pointer(n), pointer(n), u, p, p]),
            "EnqueueFillBuffer": (i, [p, p, p, n, n, n, u, p, p]),
            "Finish": (i, [p]),
            "GetEventProfilingInfo": (i, [p, u, n, p, pointer(n)]),
            "ReleaseEvent": (i, [p]),
        }
        for kind in ("MemObject", "Kernel", "Program", "CommandQueue", "Context"):
            signatures["Release" + kind] = (i, [p])
        for name, (result, arguments) in signatures.items():
            function = getattr(self.library, "cl" + name)
            function.restype, function.argtypes = result, arguments
            setattr(self, name, function)
        try:
            count = u()
            checked(self.GetPlatformIDs(0, None, C.byref(count)))
            platforms = (p * count.value)()
            checked(self.GetPlatformIDs(count, platforms, None))
            ogl = C.WinDLL("opengl32.dll")
            ogl.wglGetCurrentContext.restype = ogl.wglGetCurrentDC.restype = p
            for platform in platforms:
                address = self.GetExtensionFunctionAddressForPlatform(
                    platform, b"clGetGLContextInfoKHR"
                )
                if not address:
                    continue
                info = C.WINFUNCTYPE(i, pointer(C.c_ssize_t), u, n, p, pointer(n))(address)
                properties = (C.c_ssize_t * 7)(
                    0x1084,
                    platform,
                    0x2008,
                    ogl.wglGetCurrentContext(),
                    0x200B,
                    ogl.wglGetCurrentDC(),
                    0,
                )
                self.cl_device = p()
                if info(properties, 0x2006, C.sizeof(p), C.byref(self.cl_device), None):
                    continue
                if not self.cl_device.value:
                    continue
                error = i()
                self.context = self.CreateContext(
                    properties, 1, C.byref(self.cl_device), None, None, C.byref(error)
                )
                if self.context and not error.value:
                    break
            if not self.context:
                raise RuntimeError("No OpenCL device shares this GL context")
            device_name = C.create_string_buffer(1024)
            checked(self.GetDeviceInfo(self.cl_device, 0x102B, len(device_name), device_name, None))
            self.device_name = device_name.value.decode("utf-8", "replace")
            local_memory = C.c_ulonglong()
            checked(
                self.GetDeviceInfo(
                    self.cl_device, 0x1023, C.sizeof(local_memory), C.byref(local_memory), None
                )
            )
            self.local_memory = local_memory.value
            workgroup = n()
            checked(
                self.GetDeviceInfo(
                    self.cl_device, 0x1004, C.sizeof(workgroup), C.byref(workgroup), None
                )
            )
            if workgroup.value < 128 or self.local_memory < 16384:
                raise RuntimeError("OpenCL workgroup limits are too small")
            self.queue = self.CreateCommandQueue(
                self.context, self.cl_device, 2 if profiling else 0, C.byref(error)
            )
            checked(error.value)
        except Exception:
            self.close()
            raise

    def image(self, texture):
        if texture not in self.images:
            error = C.c_int()
            image = self.CreateFromGLTexture(self.context, 1, 0x0DE1, 0, texture, C.byref(error))
            checked(error.value)
            self.images[texture] = image
        return self.images[texture]

    def release_texture(self, texture):
        image = self.images.pop(texture, None)
        if image:
            checked(self.ReleaseMemObject(image))

    def buffer(self, name, length):
        old = self.buffers.get(name)
        if old is not None and old[1] >= length:
            return old[0]
        error = C.c_int()
        result = self.CreateBuffer(self.context, 1, length, None, C.byref(error))
        checked(error.value)
        if old is not None:
            checked(self.ReleaseMemObject(old[0]))
        self.buffers[name] = (result, length)
        return result

    def clear(self, buffer, length):
        zero = C.c_uint(0)
        checked(
            self.EnqueueFillBuffer(self.queue, buffer, C.byref(zero), 4, 0, length, 0, None, None)
        )

    @contextlib.contextmanager
    def shared(self, textures):
        objects = (C.c_void_p * len(set(textures)))(
            *(self.image(texture) for texture in sorted(set(textures)))
        )
        self.device.gl.Finish()
        checked(self.EnqueueAcquireGLObjects(self.queue, len(objects), objects, 0, None, None))
        try:
            yield
        finally:
            checked(self.EnqueueReleaseGLObjects(self.queue, len(objects), objects, 0, None, None))
            checked(self.Finish(self.queue))
            events, self.events = self.events, []
            try:
                for name, event in events:
                    start, end = C.c_ulonglong(), C.c_ulonglong()
                    checked(self.GetEventProfilingInfo(event, 0x1282, 8, C.byref(start), None))
                    checked(self.GetEventProfilingInfo(event, 0x1283, 8, C.byref(end), None))
                    self.timings.append((name, (end.value - start.value) / 1e6))
            finally:
                for _name, event in events:
                    self.ReleaseEvent(event)

    def kernel(self, name, code):
        key = (name, code)
        if key in self.kernels:
            return self.kernels[key]
        error = C.c_int()
        if code not in self.programs:
            source = C.c_char_p(code.encode("utf-8"))
            program = self.CreateProgramWithSource(
                self.context, 1, C.byref(source), None, C.byref(error)
            )
            checked(error.value)
            status = self.BuildProgram(
                program, 1, C.byref(self.cl_device), b"-cl-std=CL1.2", None, None
            )
            if status:
                log = C.create_string_buffer(32768)
                self.GetProgramBuildInfo(program, self.cl_device, 0x1183, len(log), log, None)
                self.ReleaseProgram(program)
                raise Unavailable("OpenCL " + name + ": " + log.value.decode("utf-8", "replace"))
            self.programs[code] = program
        kernel = self.CreateKernel(self.programs[code], name.encode("ascii"), C.byref(error))
        checked(error.value)
        self.kernels[key] = kernel
        return kernel

    def enqueue(self, name, code, arguments, global_size, local_size=(128,)):
        kernel = self.kernel(name, code)
        for index, value in enumerate(arguments):
            checked(self.SetKernelArg(kernel, index, C.sizeof(value), C.byref(value)))
        size = C.c_size_t
        event = C.c_void_p()
        checked(
            self.EnqueueNDRangeKernel(
                self.queue,
                kernel,
                len(global_size),
                None,
                (size * len(global_size))(*global_size),
                (size * len(local_size))(*local_size),
                0,
                None,
                C.byref(event) if self.profiling else None,
            )
        )
        if event.value:
            self.events.append((name, event.value))

    def close(self):
        if self.queue:
            self.Finish(self.queue)
        for _name, event in self.events:
            self.ReleaseEvent(event)
        self.events[:] = []
        for image in self.images.values():
            self.ReleaseMemObject(image)
        for buffer, _length in self.buffers.values():
            self.ReleaseMemObject(buffer)
        for kernel in self.kernels.values():
            self.ReleaseKernel(kernel)
        for program in self.programs.values():
            self.ReleaseProgram(program)
        if self.queue:
            self.ReleaseCommandQueue(self.queue)
        if self.context:
            self.ReleaseContext(self.context)
        self.images.clear()
        self.buffers.clear()
        self.kernels.clear()
        self.programs.clear()
        self.context = self.queue = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def fft_code(n, vector):
        kind = "float4" if vector else "float2"
        product = "(float4)(cmul(b.xy,t),cmul(b.zw,t))" if vector else "cmul(b,t)"
        return (
            """
            #define N COUNT
            typedef KIND value_t;
            int reversed(int value){int result=0;for(int b=0;b<BITS;b++){
                result=(result<<1)|(value&1);value>>=1;}return result;}
            float2 cmul(float2 a,float2 b){return (float2)(a.x*b.x-a.y*b.y,a.x*b.y+a.y*b.x);}
            int2 coordinate(int index,int row,int axis){return axis==0 ? (int2)(index,row) : (int2)(row,index);}
            void fft(__local value_t *data,int thread,read_only image2d_t twiddles){
                for(int stage=2,phase=0;stage<=N;stage*=2,phase++){int half_m=stage/2;
                    for(int pair=thread;pair<N/2;pair+=128){
                        int lane=pair&(half_m-1),base=(pair/half_m)*stage+lane;
                        value_t a=data[base],b=data[base+half_m];
                        float2 t=read_imagef(twiddles,(int2)(lane,phase)).xy;value_t v=PRODUCT;
                        data[base]=a+v;data[base+half_m]=a-v;
                    }
                    barrier(CLK_LOCAL_MEM_FENCE);
                }
            }
        """.replace("COUNT", str(n))
            .replace("BITS", str(n.bit_length() - 1))
            .replace("KIND", kind)
            .replace("PRODUCT", product)
        )

    def gaussian_axis(self, name, texture, kernel, size, axis, n, radius, twiddles):
        code = (
            self.fft_code(n, False)
            + """
            int reflect(int p,int n){if(n<=1)return 0;
                int period=2*n-2;p=p%period;if(p<0)p+=period;return p<n ? p : period-p;}
            __kernel void gaussian(read_only image2d_t source,read_only image2d_t weights,
                                   write_only image2d_t destination,read_only image2d_t forward,
                                   read_only image2d_t inverse,int axis,int radius,int length){
                int thread=get_local_id(0),row=get_group_id(0);__local float2 data[N];
                for(int i=thread;i<N;i+=128){int j=reversed(i);
                    data[i]=(float2)(j<length+2*radius ? read_imagef(source,coordinate(reflect(j-radius,length),row,axis)).x : 0.0f,0.0f);}
                barrier(CLK_LOCAL_MEM_FENCE);fft(data,thread,forward);
                for(int i=thread;i<N;i+=128)data[i]*=read_imagef(weights,(int2)(i,0)).x;
                barrier(CLK_LOCAL_MEM_FENCE);
                for(int i=thread;i<N;i+=128){int j=reversed(i);if(i<j){float2 a=data[i];data[i]=data[j];data[j]=a;}}
                barrier(CLK_LOCAL_MEM_FENCE);fft(data,thread,inverse);
                for(int i=thread;i<length;i+=128)write_imagef(destination,coordinate(i,row,axis),(float4)(data[i+radius].x/(float)N));
            }
        """
        )
        target = self.device.target(name, *size)
        textures = (texture, kernel, target) + tuple(twiddles)
        arguments = [C.c_void_p(self.image(t)) for t in textures]
        arguments += [C.c_int(v) for v in (axis, radius, size[axis])]
        self.kernel("gaussian", code)
        with self.shared(textures):
            self.enqueue("gaussian", code, arguments, (size[1 - axis] * 128,))
        return target

    def fft_axis(self, name, texture, size, axis, inverse, twiddles):
        n = size[axis]
        code = (
            self.fft_code(n, True)
            + """
            __kernel void transform(read_only image2d_t source,write_only image2d_t destination,
                                    read_only image2d_t twiddles,int axis,float normalization){
                int thread=get_local_id(0),row=get_group_id(0);__local float4 data[N];
                for(int i=thread;i<N;i+=128)data[i]=read_imagef(source,coordinate(reversed(i),row,axis));
                barrier(CLK_LOCAL_MEM_FENCE);fft(data,thread,twiddles);
                for(int i=thread;i<N;i+=128)write_imagef(destination,coordinate(i,row,axis),data[i]/normalization);
            }
        """
        )
        target = self.device.target(name, *size)
        textures = (texture, target, twiddles)
        arguments = [C.c_void_p(self.image(t)) for t in textures]
        arguments += [C.c_int(axis), C.c_float(n if inverse else 1.0)]
        self.kernel("transform", code)
        with self.shared(textures):
            self.enqueue("transform", code, arguments, (size[1 - axis] * 128,))
        return target

    def meters(self, name, size, inputs):
        rows = (size[0] * size[1] + 255) // 256
        targets = tuple(self.device.target(name + "_%d" % i, 145, rows) for i in range(4))
        code = """
            __kernel void meters(read_only image2d_t linear_map,read_only image2d_t features_map,
                read_only image2d_t gradient_map,read_only image2d_t camera_map,
                read_only image2d_t quantiles,read_only image2d_t geometry_x,read_only image2d_t geometry_y,
                write_only image2d_t out_a,write_only image2d_t out_b,
                write_only image2d_t out_c,write_only image2d_t out_d,int rows){
                int thread=get_local_id(0),placement=get_group_id(0)/rows*16+thread%16;
                int sample_lane=thread/16,chunk=get_group_id(0)%rows;
                int2 size=(int2)(get_image_width(linear_map),get_image_height(linear_map));
                float character_height=placement==144 ? 0.78f : 0.92f;
                float center_x=placement==144 ? 0.5f : (float)(placement%16)/15.0f;
                float baseline=placement==144 ? 0.99f : 0.84f*(float)(placement/16)/8.0f+character_height*0.48f;
                baseline=clamp(baseline,0.1f,1.25f);
                float char_h=fmax(4.0f,floor((float)size.y*character_height));
                float char_w=fmax(4.0f,floor(char_h*0.54f));
                float cx=floor(center_x*(float)size.x),bottom=floor(baseline*(float)size.y);
                float cy=bottom-char_h*0.48f,rx=fmax(char_w*0.86f,1.0f),ry=fmax(char_h*0.66f,1.0f);
                float subject_y=clamp(baseline-character_height*0.48f,0.0f,1.0f);
                float clip_hi=read_imagef(quantiles,(int2)(0,0)).x;
                float4 a=(float4)(0.0f),b=a,c=a,d=a;
                for(int j=sample_lane;j<256 && placement<145;j+=8){
                    int index=chunk*256+j;if(index>=size.x*size.y)break;
                    int2 p=(int2)(index%size.x,index/size.x);
                    float2 gx=read_imagef(geometry_x,(int2)(p.x,placement==144 ? 16 : placement%16)).xy;
                    float3 gy=read_imagef(geometry_y,(int2)(p.y,placement==144 ? 9 : placement/16)).xyz;
                    float distance=gx.y+gy.y;
                    float weight=distance<=0.5f ? (distance<0.28f ? 0.18f : 1.0f) : gx.x*gy.x;
                    float4 linear=read_imagef(linear_map,p),features=read_imagef(features_map,p);
                    float clipped=fmin(linear.w,clip_hi);
                    float2 gradient=placement==144 ? read_imagef(camera_map,p).xy : read_imagef(gradient_map,p).xy;
                    float upper=gy.z;
                    a+=(float4)(linear.xyz,1.0f)*weight;
                    b+=(float4)(clipped,features.xyz)*weight;
                    c+=(float4)(gradient,features.w,0.0f)*weight;
                    d+=(float4)(linear.xyz,1.0f)*(weight*upper);
                }
                __local float4 aa[128],bb[128],cc[128],dd[128];
                aa[thread]=a;bb[thread]=b;cc[thread]=c;dd[thread]=d;
                barrier(CLK_LOCAL_MEM_FENCE);
                for(int step=4;step>0;step/=2){
                    if(sample_lane<step){aa[thread]+=aa[thread+step*16];bb[thread]+=bb[thread+step*16];
                        cc[thread]+=cc[thread+step*16];dd[thread]+=dd[thread+step*16];}
                    barrier(CLK_LOCAL_MEM_FENCE);
                }
                if(sample_lane==0 && placement<145){int2 p=(int2)(placement,chunk);
                    write_imagef(out_a,p,aa[thread]);write_imagef(out_b,p,bb[thread]);
                    write_imagef(out_c,p,cc[thread]);write_imagef(out_d,p,dd[thread]);}
            }
        """
        textures = tuple(inputs) + targets
        arguments = [C.c_void_p(self.image(texture)) for texture in textures] + [C.c_int(rows)]
        self.kernel("meters", code)
        with self.shared(textures):
            self.enqueue("meters", code, arguments, (10 * rows * 128,))
        return targets

    def quantiles(self, name, texture, maximum, size, channel, values, positive, unit_range):
        histogram = self.buffer("quantile_histogram", 8192 * 4)
        parameters = self.buffer("quantile_parameters", 8 * 16)
        selected = self.buffer("quantile_selected", 8 * 4)
        target = self.device.target(name, len(values), 1)
        code = """
            float component(float4 value,int index){
                return index==0 ? value.x : (index==1 ? value.y : (index==2 ? value.z : value.w));}
            __kernel void histogram(read_only image2d_t source,read_only image2d_t maximum,
                __global uint *bins,__global float4 *parameters,int channel,int positive,int unit_range,int fine){
                int row=get_group_id(1),thread=get_local_id(0);
                int chosen=fine ? (int)parameters[row].x : 0;
                if(fine)for(int prior=0;prior<row;prior++)if((int)parameters[prior].x==chosen)return;
                __local uint counts[1024];
                for(int bin=thread;bin<1024;bin+=128)counts[bin]=0;
                barrier(CLK_LOCAL_MEM_FENCE);
                int2 size=(int2)(get_image_width(source),get_image_height(source));
                float limit=unit_range ? 1.0f : component(read_imagef(maximum,(int2)(0,0)),channel);
                for(int sample=0;sample<4;sample++){
                    int index=get_group_id(0)*512+thread+sample*128;
                    if(index>=size.x*size.y)continue;
                    float value=component(read_imagef(source,(int2)(index%size.x,index/size.x)),channel);
                    if(positive && value<=0.000001f)continue;
                    float scaled=clamp(value/fmax(limit,1e-20f),0.0f,1.0f)*1024.0f;
                    int coarse=min((int)scaled,1023),bin=coarse;
                    if(fine){if(coarse!=chosen)continue;bin=min((int)((scaled-(float)coarse)*1024.0f),1023);}
                    atomic_inc(counts+bin);
                }
                barrier(CLK_LOCAL_MEM_FENCE);
                for(int bin=thread;bin<1024;bin+=128)if(counts[bin])atomic_add(bins+row*1024+bin,counts[bin]);
            }
            void prefix(__global uint *bins,int row,__local uint *blocks,uint *values){
                int thread=get_local_id(0);uint total=0;
                for(int k=0;k<8;k++){values[k]=bins[row*1024+thread*8+k];total+=values[k];}
                blocks[thread]=total;barrier(CLK_LOCAL_MEM_FENCE);
                for(int offset=1;offset<128;offset*=2){uint preceding=thread>=offset ? blocks[thread-offset] : 0;
                    barrier(CLK_LOCAL_MEM_FENCE);blocks[thread]+=preceding;barrier(CLK_LOCAL_MEM_FENCE);}
            }
            __kernel void parameters(__global uint *bins,__global float4 *output,float4 quantiles,int ranks){
                int thread=get_local_id(0);__local uint blocks[128];uint values[8];
                prefix(bins,0,blocks,values);uint count=blocks[127],before=thread==0 ? 0 : blocks[thread-1];
                for(int index=0;index<ranks;index++){
                    float position=fmax((float)count-1.0f,0.0f)*component(quantiles,index/2);
                    uint rank=(uint)(index%2==0 ? floor(position) : ceil(position));
                    if(count==0){if(thread==0)output[index]=(float4)(1023.0f,0.0f,0.0f,0.0f);}
                    else if(before<=rank && blocks[thread]>rank){uint cumulative=before;
                        for(int k=0;k<8;k++){if(cumulative+values[k]>rank){
                            output[index]=(float4)((float)(thread*8+k),(float)(rank-cumulative),(float)count,position-floor(position));break;}
                            cumulative+=values[k];}
                    }
                }
            }
            __kernel void select_values(__global uint *bins,__global float4 *parameters,__global float *output){
                int index=get_group_id(0),thread=get_local_id(0);float4 info=parameters[index];
                if(info.z<0.5f){if(thread==0)output[index]=0.0f;return;}
                int row=index;for(int other=0;other<index;other++)if(other<row && parameters[other].x==info.x)row=other;
                __local uint blocks[128];uint values[8];prefix(bins,row,blocks,values);
                uint before=thread==0 ? 0 : blocks[thread-1],rank=(uint)info.y;
                if(before<=rank && blocks[thread]>rank){uint cumulative=before;
                    for(int k=0;k<8;k++){if(cumulative+values[k]>rank){
                        output[index]=fmin((info.x*1024.0f+(float)(thread*8+k)+0.5f)/1048576.0f,1.0f);break;}
                        cumulative+=values[k];}
                }
            }
            __kernel void result(__global float *selected,__global float4 *parameters,
                read_only image2d_t maximum,write_only image2d_t destination,int channel,int unit_range,int count){
                int i=get_global_id(0);if(i>=count)return;
                float scale=unit_range ? 1.0f : component(read_imagef(maximum,(int2)(0,0)),channel);
                float4 info=parameters[i*2];
                float a=selected[i*2]*scale,b=selected[i*2+1]*scale;
                write_imagef(destination,(int2)(i,0),(float4)(a*(1.0f-info.w)+b*info.w,info.z,0.0f,1.0f));
            }
        """
        for kernel in ("histogram", "parameters", "select_values", "result"):
            self.kernel(kernel, code)
        p, i = C.c_void_p, C.c_int
        source, limit, destination = [p(self.image(t)) for t in (texture, maximum, target)]
        common = [
            source,
            limit,
            p(histogram),
            p(parameters),
            i(channel),
            i(positive),
            i(unit_range),
        ]
        ranks = len(values) * 2
        with self.shared((texture, maximum, target)):
            self.clear(histogram, 8192 * 4)
            groups = (size[0] * size[1] + 511) // 512
            self.enqueue("histogram", code, common + [i(0)], (groups * 128, 1), (128, 1))
            self.enqueue(
                "parameters",
                code,
                [
                    p(histogram),
                    p(parameters),
                    (C.c_float * 4)(*(tuple(values) + (0.0,) * (4 - len(values)))),
                    i(ranks),
                ],
                (128,),
            )
            self.clear(histogram, 8192 * 4)
            self.enqueue("histogram", code, common + [i(1)], (groups * 128, ranks), (128, 1))
            self.enqueue(
                "select_values", code, [p(histogram), p(parameters), p(selected)], (ranks * 128,)
            )
            self.enqueue(
                "result",
                code,
                [
                    p(selected),
                    p(parameters),
                    limit,
                    destination,
                    i(channel),
                    i(unit_range),
                    i(len(values)),
                ],
                (128,),
            )
        return target

    def labels(self, name, mask, size):
        count = size[0] * size[1]
        parents = self.buffer("component_parents", count * 4)
        target = self.device.target(name + "_opencl_labels", *size)
        code = """
            uint root(__global uint *parent,uint p,uint count){
                uint q=atomic_add(parent+p,0u);
                for(uint step=0;step<count && q!=p;step++){
                    uint next=atomic_add(parent+q,0u);atomic_min(parent+p,next);p=q;q=next;
                }
                return p;
            }
            void join(__global uint *parent,uint a,uint b,uint count){
                for(uint step=0;step<count;step++){
                    a=root(parent,a,count);b=root(parent,b,count);if(a==b)return;
                    uint high=max(a,b),low=min(a,b),old=atomic_min(parent+high,low);
                    if(old==high)return;a=old;b=low;
                }
            }
            __kernel void initialize(read_only image2d_t mask,__global uint *parent,int width,int count){
                int i=get_global_id(0);if(i>=count)return;
                parent[i]=read_imagef(mask,(int2)(i%width,i/width)).x>0.5f ? (uint)i : 0xffffffffu;
            }
            __kernel void connect(__global uint *parent,int width,int count){
                uint i=get_global_id(0);if(i>=(uint)count || atomic_add(parent+i,0u)==0xffffffffu)return;
                int2 p=(int2)(i%(uint)width,i/(uint)width);
                for(int k=0;k<4;k++){
                    int2 q=p+(k==0 ? (int2)(1,0) : (int2)(k-2,1));
                    if(q.x<0 || q.x>=width || q.y>=count/width)continue;
                    uint j=q.y*width+q.x;if(atomic_add(parent+j,0u)!=0xffffffffu)join(parent,i,j,count);
                }
            }
            __kernel void output(__global uint *parent,write_only image2d_t destination,int width,int count){
                uint i=get_global_id(0);if(i>=(uint)count)return;
                float value=parent[i]==0xffffffffu ? 0.0f : (float)(root(parent,i,count)+1u);
                write_imagef(destination,(int2)(i%(uint)width,i/(uint)width),(float4)(value,0.0f,0.0f,1.0f));
            }
        """
        for kernel in ("initialize", "connect", "output"):
            self.kernel(kernel, code)
        p, i = C.c_void_p, C.c_int
        common = [p(parents), i(size[0]), i(count)]
        global_size = (((count + 127) // 128) * 128,)
        with self.shared((mask, target)):
            self.enqueue("initialize", code, [p(self.image(mask))] + common, global_size)
            self.enqueue("connect", code, common, global_size)
            self.enqueue(
                "output",
                code,
                [p(parents), p(self.image(target)), i(size[0]), i(count)],
                global_size,
            )
        return target

    def sort_candidates(self, name, source, root_channel="g", size=None):
        count = self.buffer("candidate_count", 4)
        values = self.buffer("candidate_values", 128 * 16)
        target = self.device.target(name + "_opencl_sorted", 128, 1)
        code = """
            __kernel void collect(read_only image2d_t source,__global uint *count,__global float4 *values){
                uint index=get_global_id(0);int width=get_image_width(source);
                if(index>=(uint)(width*get_image_height(source)))return;
                float4 value=read_imagef(source,(int2)(index%(uint)width,index/(uint)width));
                if(value.x>0.0f){uint slot=atomic_inc(count);if(slot<128u)values[slot]=value;}
            }
            __kernel void sort(read_only image2d_t source,__global uint *count,__global float4 *values,
                               write_only image2d_t destination,int compact){
                int i=get_local_id(0);__local float4 items[128];
                items[i]=compact ? ((uint)i<*count ? values[i] : (float4)(0.0f)) : read_imagef(source,(int2)(i,0));
                barrier(CLK_LOCAL_MEM_FENCE);
                for(int stage=2;stage<=128;stage*=2)for(int step=stage/2;step>0;step/=2){
                    int j=i^step;float4 a=items[i],b=items[j];
                    int better=a.x>b.x || (a.x==b.x && a.ROOT<b.ROOT);
                    int want=((i&stage)==0)==((i&step)==0);
                    barrier(CLK_LOCAL_MEM_FENCE);items[i]=better==want ? a : b;barrier(CLK_LOCAL_MEM_FENCE);
                }
                write_imagef(destination,(int2)(i,0),items[i]);
            }
        """.replace("ROOT", "y" if root_channel == "g" else "z")
        self.kernel("sort", code)
        if size is not None:
            self.kernel("collect", code)
        p = C.c_void_p
        arguments = [p(self.image(source)), p(count), p(values)]
        with self.shared((source, target)):
            if size is not None:
                self.clear(count, 4)
                self.enqueue(
                    "collect", code, arguments, (((size[0] * size[1] + 127) // 128) * 128,)
                )
            self.enqueue(
                "sort", code, arguments + [p(self.image(target)), C.c_int(size is not None)], (128,)
            )
        return target

    def component_quantiles(self, name, labels, selection, linear, size):
        count = size[0] * size[1]
        slots = self.buffer("component_slots", count * 4)
        bins = self.buffer("component_histogram", 1024 * 1024 * 4)
        parameters = self.buffer("component_parameters", 1024 * 16)
        selected = self.buffer("component_selected", 1024 * 4)
        target = self.device.target(name + "_opencl_quantiles", 128, 2)
        pad = max(5, (min(size) // 46) | 1) // 2
        code = """
            #define PAD PADDING
            #define SIDE TILE_SIDE
            __kernel void slots(read_only image2d_t candidates,__global uint *slots){
                uint index=get_global_id(0);float4 c=read_imagef(candidates,(int2)(index,0));
                if(c.x>0.0f)slots[(int)c.y-1]=index+1;
            }
            void add_value(__global uint *bins,__global float4 *parameters,int group,float value,int fine){
                int bin=min((int)value,1023),row=group;
                if(fine){row=-1;
                    for(int k=0;k<4;k++)if(row<0 && (int)parameters[group*4+k].x==bin)row=group*4+k;
                    if(row<0)return;bin=min((int)((value-(float)bin)*1024.0f),1023);
                }
                atomic_inc(bins+row*1024+bin);
            }
            __kernel void histogram(read_only image2d_t labels,read_only image2d_t linear,
                __global uint *slots,__global uint *bins,__global float4 *parameters,int fine){
                int2 size=(int2)(get_image_width(labels),get_image_height(labels));
                int thread=get_local_id(1)*8+get_local_id(0);
                int2 origin=(int2)(get_group_id(0)*8-PAD,get_group_id(1)*8-PAD);
                __local uint tile[SIDE*SIDE];
                for(int i=thread;i<SIDE*SIDE;i+=64){int2 p=origin+(int2)(i%SIDE,i/SIDE);uint slot=0;
                    if(p.x>=0 && p.y>=0 && p.x<size.x && p.y<size.y){
                        int root=(int)read_imagef(labels,p).x-1;if(root>=0)slot=slots[root];}
                    tile[i]=slot;
                }
                barrier(CLK_LOCAL_MEM_FENCE);
                int2 p=(int2)(get_global_id(0),get_global_id(1));if(p.x>=size.x || p.y>=size.y)return;
                int2 local_p=(int2)(get_local_id(0)+PAD,get_local_id(1)+PAD);
                uint own=tile[local_p.y*SIDE+local_p.x];
                float value=clamp(read_imagef(linear,p).w,0.0f,1.0f)*1024.0f;
                if(own>0)add_value(bins,parameters,own-1,value,fine);
                uint seen[4]={0,0,0,0};
                for(int y=-PAD;y<=PAD;y++)for(int x=-PAD;x<=PAD;x++){
                    uint slot=tile[(local_p.y+y)*SIDE+local_p.x+x];if(slot==0 || slot==own)continue;
                    uint group=slot-1,word=group/32,bit=1u<<(group%32);
                    if(seen[word]&bit)continue;seen[word]|=bit;add_value(bins,parameters,128+group,value,fine);
                }
            }
            void prefix(__global uint *bins,int row,__local uint *blocks,uint *values){
                int thread=get_local_id(0);uint total=0;
                for(int k=0;k<8;k++){values[k]=bins[row*1024+thread*8+k];total+=values[k];}
                blocks[thread]=total;barrier(CLK_LOCAL_MEM_FENCE);
                for(int offset=1;offset<128;offset*=2){uint preceding=thread>=offset ? blocks[thread-offset] : 0;
                    barrier(CLK_LOCAL_MEM_FENCE);blocks[thread]+=preceding;barrier(CLK_LOCAL_MEM_FENCE);}
            }
            __kernel void parameters(__global uint *bins,__global float4 *parameters){
                int group=get_group_id(0),thread=get_local_id(0);__local uint blocks[128];uint values[8];
                prefix(bins,group,blocks,values);uint count=blocks[127],before=thread==0 ? 0 : blocks[thread-1];
                for(int k=0;k<4;k++){
                    float position=fmax((float)count-1.0f,0.0f)*(k<2 ? 0.5f : 0.9f);
                    uint rank=(uint)(k%2==0 ? floor(position) : ceil(position));
                    if(count==0){if(thread==0)parameters[group*4+k]=(float4)(1023.0f,0.0f,0.0f,0.0f);}
                    else if(before<=rank && blocks[thread]>rank){uint cumulative=before;
                        for(int i=0;i<8;i++){if(cumulative+values[i]>rank){
                            parameters[group*4+k]=(float4)((float)(thread*8+i),(float)(rank-cumulative),(float)count,position-floor(position));break;}
                            cumulative+=values[i];}
                    }
                }
            }
            __kernel void selected(__global uint *bins,__global float4 *parameters,__global float *selected){
                int index=get_group_id(0),thread=get_local_id(0);float4 info=parameters[index];
                if(info.z<0.5f){if(thread==0)selected[index]=0.0f;return;}
                int row=index;for(int i=index/4*4;i<index;i++)if(i<row && parameters[i].x==info.x)row=i;
                __local uint blocks[128];uint values[8];prefix(bins,row,blocks,values);
                uint before=thread==0 ? 0 : blocks[thread-1],rank=(uint)info.y;
                if(before<=rank && blocks[thread]>rank){uint cumulative=before;
                    for(int i=0;i<8;i++){if(cumulative+values[i]>rank){
                        selected[index]=fmin((info.x*1024.0f+(float)(thread*8+i)+0.5f)/1048576.0f,1.0f);break;}
                        cumulative+=values[i];}
                }
            }
            __kernel void result(__global float *selected,__global float4 *parameters,write_only image2d_t destination){
                int i=get_global_id(0);float4 a=parameters[i*4],b=parameters[i*4+2];
                float median=selected[i*4]*(1.0f-a.w)+selected[i*4+1]*a.w;
                float upper=selected[i*4+2]*(1.0f-b.w)+selected[i*4+3]*b.w;
                write_imagef(destination,(int2)(i%128,i/128),(float4)(median,upper,a.z,1.0f));
            }
        """.replace("PADDING", str(pad)).replace("TILE_SIDE", str(8 + 2 * pad))
        for kernel in ("slots", "histogram", "parameters", "selected", "result"):
            self.kernel(kernel, code)
        p = C.c_void_p
        images = [p(self.image(t)) for t in (labels, selection, linear, target)]
        with self.shared((labels, selection, linear, target)):
            self.clear(slots, count * 4)
            self.enqueue("slots", code, [images[1], p(slots)], (128,))
            common = [images[0], images[2], p(slots), p(bins), p(parameters)]
            extent = (((size[0] + 7) // 8) * 8, ((size[1] + 7) // 8) * 8)
            self.clear(bins, 1024 * 1024 * 4)
            self.enqueue("histogram", code, common + [C.c_int(0)], extent, (8, 8))
            self.enqueue("parameters", code, [p(bins), p(parameters)], (256 * 128,))
            self.clear(bins, 1024 * 1024 * 4)
            self.enqueue("histogram", code, common + [C.c_int(1)], extent, (8, 8))
            self.enqueue("selected", code, [p(bins), p(parameters), p(selected)], (1024 * 128,))
            self.enqueue("result", code, [p(selected), p(parameters), images[3]], (256,))
        return target
