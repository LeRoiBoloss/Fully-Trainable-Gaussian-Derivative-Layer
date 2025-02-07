"""
==============
Tensorflow implementation of the layer proposed in 

[1] Valentin Penaud--Polge, Santiago Velasco-Forero, Jesus Angulo,
    Fully Trainable Gaussian Derivative Convolutional Layer
    29th IEEE International Conference on Image Processing, 2022

Please cite this reference when using this code.
==============
"""

import tensorflow
import tensorflow.keras.backend as K
from tensorflow.python.ops import nn


import numpy as np
import math

class MaxGroupPool(tensorflow.keras.layers.Layer):
    def __init__(self, num_rota, **kwargs):
        super(MaxGroupPool, self).__init__()
        self.num_rota = num_rota

    def build(self, input_shape):
        self.inputShape = input_shape

    def call(self, inputs):

        output = tensorflow.reshape(inputs, [-1, self.inputShape[1], self.inputShape[2], self.num_rota, self.inputShape[3] // self.num_rota])
        output = tensorflow.reduce_max(output, 3)

        return output
    
    def get_config(self):
        config = super(MaxGroupPool, self).get_config()
        config.update({
            "num_rota":self.num_rota,
        })
        return config

class AvgGroupPool(tensorflow.keras.layers.Layer):
    def __init__(self, num_rota, **kwargs):
        super(MaxGroupPool, self).__init__()
        self.num_rota = num_rota

    def build(self, input_shape):
        self.inputShape = input_shape

    def call(self, inputs):

        output = tensorflow.reshape(inputs, [-1, self.inputShape[1], self.inputShape[2], self.num_rota, self.inputShape[3] // self.num_rota])
        output = tensorflow.reduce_mean(output, 3)

        return output
    
    def get_config(self):
        config = super(MaxGroupPool, self).get_config()
        config.update({
            "num_rota":self.num_rota,
        })
        return config

class MaxActivationGroupPool(tensorflow.keras.layers.Layer):
    def __init__(self, num_rota, **kwargs):
        super(MaxGroupPool, self).__init__()
        self.num_rota = num_rota

    def build(self, input_shape):
        self.inputShape = input_shape

    def call(self, inputs):

        output = tensorflow.reshape(inputs, [-1, self.inputShape[1], self.inputShape[2], self.num_rota, self.inputShape[3] // self.num_rota])
        max = tensorflow.reduce_max(output, [1, 2])
        
        max = tensorflow.argmax(max, -2)
        
        out = []
        for k, index in enumerate(max):
            out.append(output[:,:,:,index,k])

        output = tensorflow.concat(out, -1)
        return output
    
    def get_config(self):
        config = super(MaxGroupPool, self).get_config()
        config.update({
            "num_rota":self.num_rota,
        })
        return config     

class FTGDConvLayerRotation(tensorflow.keras.layers.Layer):
    """
    Linear combinations of anisotropic, shifted and oriented Gaussian Derivative kernels.

    Params : filters      - int             - the number of filters.
             kernel_size  - tuple of int    - kernel size used.
             num_basis    - int             - number of bases used in the layer.
             order        - int             - maximal order of derivation of the 
                                              Gaussian Derivative kernels.
             num_rota     - int             - number of rotation 
                                              example : num_rota = 4 => 0°, 90°, 180°, 270°
             separated    - boolean         - indicates if the linear combination 
                                              should be separated or not.
             trainability - list of boolean - indicates if the Gaussian parameters
                                              should be trainable or not.
                                              example : trainability = [True, False, True]
                                                -> scales will be trainable
                                                -> shifts won't be trainable
                                                -> orientations will be trainable
             padding      - string          - type of padding
             sigma_init   - float           - initialization value of the scales 
                                              (if random_init = False)
             mu_init      - float           - initialization value of the shifts
                                              (if random_init = False)
             theta_init   - float           - initialization value of the orientation
                                              (if random_init = False)
                                              example : if sigma_init = 1.5, 
                                                        trainability[0] = False and 
                                                        random_init = False then
                                                        the Gaussian Derivative kernels 
                                                        will all have constant scales 
                                                        of value 1.5.
             strides      - tuple of int    - value of the stride
             random_init  - boolean         - whether or not the initialization should 
                                              be random. If false, sigma_init, mu_init and 
                                              theta_init are used.
             use_bias     - boolean         - whether a bias should be used or not.
                                                

                                        
    :Example:
    >>>from keras.models import Sequential, Model
    >>>from keras.layers import Input
    >>>xIn=Input(shape=(28,28,3))
    >>>x=FTGDConvLayerRotation(filters=16, 
                       kernel_size = (7,7), 
                       num_basis= 4, order=3, 
                       separated = True, 
                       name = 'Gaussian1')(xIn)
    >>>model = Model(xIn,x)
    """
    
    def __init__(self, filters, kernel_size,  num_basis, order, num_rota=1, separated = False, trainability = [True, True, True], padding = 'same', sigma_init = 1, mu_init = 0, theta_init = 0, strides = (1,1), random_init = True, use_bias = False, **kwargs):

        super(FTGDConvLayerRotation, self).__init__()
        self.num_rota = num_rota
        self.num_filters = filters
        self.filter_size = kernel_size
        self.num_basis = num_basis
        self.order = order
        self.separated = separated
        self.trainability = trainability
        self.padding_mode = padding
        self.stride = strides
        self.random_init = random_init
        self.sigma_init = sigma_init
        self.mu_init =mu_init
        self.theta_init = theta_init
        self.use_bias = use_bias

    def build(self, input_shape):
        
        self.sigmas, self.centroids, self.thetas = initGaussianParameters(self.num_basis, self.order, self.random_init, self.trainability, self.sigma_init, self.mu_init, self.theta_init)

        if self.use_bias:
            self.bias = tensorflow.Variable(initial_value = tensorflow.zeros(shape = (self.num_filters,), dtype = 'float'),  name = 'bias', trainable = True)
        else:
            self.bias = None

        self.clWeights = initWeights(input_shape[-1], self.num_filters, self.num_basis, self.order, self.separated)
        self.inputChannels = input_shape[-1]
        self.deployed = False

    def call(self, inputs):

        if self.deployed:

            if self.separated:
                rotated_outputs = [computeOutput([RotatedGaussFilters, self.clWeights[1]], inputs, self.num_basis, self.separated, self.padding_mode, self.stride) for RotatedGaussFilters in self.GaussFilters]

            else:

                rotated_outputs = [computeOutput(RotatedGaussFilters, inputs, self.num_basis, self.separated, self.padding_mode, self.stride) for RotatedGaussFilters in self.GaussFilters]

            if self.use_bias:
                rotated_outputs = [nn.bias_add(outputs, self.bias, data_format='NHWC') for outputs in rotated_outputs]
                
            rotated_outputs = tensorflow.concat(rotated_outputs, -1)
            
            return rotated_outputs

        else:
            # Roll the weight to get the n filters of size (h,w,n*f1,f2)
            if self.separated:
                rolled_clWeights = [[tensorflow.roll(self.clWeights[0], i*self.inputChannels//self.num_rota, 1), self.clWeights[1]] for i in range(self.num_rota)]
            else:
                rolled_clWeights = [tensorflow.roll(self.clWeights, i*self.inputChannels//self.num_rota, 1) for i in range(self.num_rota)]

            GaussFilters = [getGaussianFilters(getBases(self.filter_size, self.num_basis, self.order, self.sigmas, self.centroids, self.thetas+tensorflow.convert_to_tensor(2*math.pi*k/self.num_rota)), w, self.num_basis, self.inputChannels, self.num_filters, self.separated) for k, w in enumerate(rolled_clWeights)]
 
            if self.separated:
                rotated_outputs = [computeOutput([RotatedGaussFilters, self.clWeights[1]], inputs, self.num_basis, self.separated, self.padding_mode, self.stride) for RotatedGaussFilters in GaussFilters]
            else :
                rotated_outputs = [computeOutput(RotatedGaussFilters, inputs, self.num_basis, self.separated, self.padding_mode, self.stride) for RotatedGaussFilters in GaussFilters]
            
            if self.use_bias:
                rotated_outputs = [nn.bias_add(outputs, self.bias, data_format='NHWC') for outputs in rotated_outputs]             
            
            rotated_outputs = tensorflow.concat(rotated_outputs, -1)
            
            return rotated_outputs

    def deploy(self):

        """
        Function to use when the training is done. It allows to avoid to compute again
        the Gaussian Derivative kernels of all bases after the training.
        """
        if self.separated:
            rolled_clWeights = [[tensorflow.roll(self.clWeights[0], i*self.inputChannels//self.num_rota, 1), self.clWeights[1]] for i in range(self.num_rota)]
        else:
            rolled_clWeights = [tensorflow.roll(self.clWeights, i*self.inputChannels//self.num_rota, 1) for i in range(self.num_rota)]

        self.GaussFilters = [getGaussianFilters(getBases(self.filter_size, self.num_basis, self.order, self.sigmas, self.centroids, self.thetas+tensorflow.convert_to_tensor(2*math.pi*k/self.num_rota)), w, self.num_basis, self.inputChannels, self.num_filters, self.separated) for k, w in enumerate(rolled_clWeights)] 
        self.deployed = True

    def to_train(self):

        """
        Fonction to use to re-train a model after deploying it.
        """
        self.deployed = False

    def get_config(self):
        config = super(FTGDConvLayerRotation, self).get_config()
        config.update({
            "num_rota":self.num_rota,
            "filters":self.num_filters,
            "kernel_size":self.filter_size,
            'num_basis':self.num_basis,
            'order':self.order,
            'separated':self.separated,
            'trainability':self.trainability,
            'strides':self.stride,
            'random_init':self.random_init,
            'padding':self.padding_mode,
            'sigma_init':self.sigma_init,
            'mu_init':self.mu_init,
            'theta_init':self.theta_init,
            'use_bias':self.use_bias
        })
        return config

class FTGDConvLayerRotationLifting(tensorflow.keras.layers.Layer):
    """
    Linear combinations of anisotropic, shifted and oriented Gaussian Derivative kernels.

    Params : filters      - int             - the number of filters.
             kernel_size  - tuple of int    - kernel size used.
             num_basis    - int             - number of bases used in the layer.
             order        - int             - maximal order of derivation of the 
                                              Gaussian Derivative kernels.
             num_rota     - int             - number of rotation 
                                              example : num_rota = 4 => 0°, 90°, 180°, 270°
             separated    - boolean         - indicates if the linear combination 
                                              should be separated or not.
             trainability - list of boolean - indicates if the Gaussian parameters
                                              should be trainable or not.
                                              example : trainability = [True, False, True]
                                                -> scales will be trainable
                                                -> shifts won't be trainable
                                                -> orientations will be trainable
             padding      - string          - type of padding
             sigma_init   - float           - initialization value of the scales 
                                              (if random_init = False)
             mu_init      - float           - initialization value of the shifts
                                              (if random_init = False)
             theta_init   - float           - initialization value of the orientation
                                              (if random_init = False)
                                              example : if sigma_init = 1.5, 
                                                        trainability[0] = False and 
                                                        random_init = False then
                                                        the Gaussian Derivative kernels 
                                                        will all have constant scales 
                                                        of value 1.5.
             strides      - tuple of int    - value of the stride
             random_init  - boolean         - whether or not the initialization should 
                                              be random. If false, sigma_init, mu_init and 
                                              theta_init are used.
             use_bias     - boolean         - whether a bias should be used or not.
                                                

                                        
    :Example:
    >>>from keras.models import Sequential, Model
    >>>from keras.layers import Input
    >>>xIn=Input(shape=(28,28,3))
    >>>x=FTGDConvLayerRotation(filters=16, 
                       kernel_size = (7,7), 
                       num_basis= 4, order=3, 
                       separated = True, 
                       name = 'Gaussian1')(xIn)
    >>>model = Model(xIn,x)
    """
    
    def __init__(self, filters, kernel_size,  num_basis, order, num_rota=1, separated = False, trainability = [True, True, True], padding = 'same', sigma_init = 1, mu_init = 0, theta_init = 0, strides = (1,1), random_init = True, use_bias = False, **kwargs):

        super(FTGDConvLayerRotationLifting, self).__init__()
        self.num_rota = num_rota
        self.num_filters = filters
        self.filter_size = kernel_size
        self.num_basis = num_basis
        self.order = order
        self.separated = separated
        self.trainability = trainability
        self.padding_mode = padding
        self.stride = strides
        self.random_init = random_init
        self.sigma_init = sigma_init
        self.mu_init =mu_init
        self.theta_init = theta_init
        self.use_bias = use_bias

    def build(self, input_shape):
        
        self.sigmas, self.centroids, self.thetas = initGaussianParameters(self.num_basis, self.order, self.random_init, self.trainability, self.sigma_init, self.mu_init, self.theta_init)

        if self.use_bias:
            self.bias = tensorflow.Variable(initial_value = tensorflow.zeros(shape = (self.num_filters,), dtype = 'float'),  name = 'bias', trainable = True)
        else:
            self.bias = None
            
        self.clWeights = initWeights(input_shape[-1], self.num_filters, self.num_basis, self.order, self.separated)
        self.inputChannels = input_shape[-1]
        self.deployed = False

    def call(self, inputs):

        if self.deployed:

            if self.separated:
                rotated_outputs = [computeOutput([RotatedGaussFilters, self.clWeights[1]], inputs, self.num_basis, self.separated, self.padding_mode, self.stride) for RotatedGaussFilters in self.GaussFilters]

            else:
                rotated_outputs = [computeOutput(RotatedGaussFilters, inputs, self.num_basis, self.separated, self.padding_mode, self.stride) for RotatedGaussFilters in self.GaussFilters]

            if self.use_bias:
                rotated_outputs = [nn.bias_add(outputs, self.bias, data_format='NHWC') for outputs in rotated_outputs]

            rotated_outputs = tensorflow.concat(rotated_outputs, -1)

            return rotated_outputs

        else:
            GaussFilters = [getGaussianFilters(getBases(self.filter_size, self.num_basis, self.order, self.sigmas, self.centroids, self.thetas+tensorflow.convert_to_tensor(2*math.pi*k/self.num_rota)), self.clWeights, self.num_basis, self.inputChannels, self.num_filters, self.separated) for k in range(self.num_rota)]
 
            if self.separated:
                rotated_outputs = [computeOutput([RotatedGaussFilters, self.clWeights[1]], inputs, self.num_basis, self.separated, self.padding_mode, self.stride) for RotatedGaussFilters in GaussFilters]
            else :
                rotated_outputs = [computeOutput(RotatedGaussFilters, inputs, self.num_basis, self.separated, self.padding_mode, self.stride) for RotatedGaussFilters in GaussFilters]

            if self.use_bias:
                rotated_outputs = [nn.bias_add(outputs, self.bias, data_format='NHWC') for outputs in rotated_outputs]

            rotated_outputs = tensorflow.concat(rotated_outputs, -1)

            return rotated_outputs

    def deploy(self):

        """
        Function to use when the training is done. It allows to avoid to compute again
        the Gaussian Derivative kernels of all bases after the training.
        """
        self.GaussFilters = [getGaussianFilters(getBases(self.filter_size, self.num_basis, self.order, self.sigmas, self.centroids, self.thetas+tensorflow.convert_to_tensor(2*math.pi*k/self.num_rota)), self.clWeights, self.num_basis, self.inputChannels, self.num_filters, self.separated) for k in range(self.num_rota)]
 
        self.deployed = True

    def to_train(self):

        """
        Fonction to use to re-train a model after deploying it.
        """
        self.deployed = False

    def get_config(self):
        config = super(FTGDConvLayerRotationLifting, self).get_config()
        config.update({
            "num_rota":self.num_rota,
            "filters":self.num_filters,
            "kernel_size":self.filter_size,
            'num_basis':self.num_basis,
            'order':self.order,
            'separated':self.separated,
            'trainability':self.trainability,
            'strides':self.stride,
            'random_init':self.random_init,
            'padding':self.padding_mode,
            'sigma_init':self.sigma_init,
            'mu_init':self.mu_init,
            'theta_init':self.theta_init,
            'use_bias':self.use_bias
        })
        return config

@tensorflow.function
def hermitePolynomials(order, x, sigma):

    """
    Description : Code a Hermite polynomial using the expression in a form of a serie.

    Params : order - int
             x     - Tensor from Tensorflow.meshgrid
             sigma - float (should be positive)

    Return : A tensor containing a Hermite polynomial of order 'order' and scale 'sigma'
    
    Usage : Used in the function computeGaussianDerivative
    """

    res = tensorflow.math.pow((np.sqrt(2)/sigma)* x,order)
    for i in range(1, (order//2)+1):
        term = (tensorflow.math.multiply(math.pow(-1, i)*math.factorial(order)/(math.factorial(i)*math.factorial(order - 2*i)), tensorflow.math.pow((tensorflow.math.divide(np.sqrt(2),sigma)),(order - 2*i)))) * tensorflow.math.pow(x, (order - 2*i))
        res = tensorflow.math.add(res, term)
    return res

@tensorflow.function
def computeGaussianDerivative(order, x, sigma):

    """
    Description : Code a Gaussian Derivative kernel G_{order}(x, sigma).
                  
    Params : order - int
             x     - Tensor from Tensorflow.meshgrid
             sigma - float (should be positive) 
    Return : A tensor containing a Gaussian Derivative of order 'order' and scale 'sigma'
    
    Usage : Used in the function computeGaussianBasis
    """
    
    hermitePart = tensorflow.math.multiply(tensorflow.math.pow(tensorflow.math.divide(-1,tensorflow.math.multiply(math.sqrt(2),sigma)),order), hermitePolynomials(order, x, sigma))
    gaussianPart = tensorflow.math.multiply(tensorflow.math.divide(1,tensorflow.math.multiply(sigma,np.sqrt(2*np.pi))), tensorflow.math.exp(- tensorflow.math.divide(tensorflow.math.pow(x, 2),(2*tensorflow.math.pow(sigma,2)))))
    
    gaussianDerivative = tensorflow.math.multiply(hermitePart, gaussianPart)
    return gaussianDerivative

@tensorflow.function
def computeGaussianBasis(size, order, sigmas, centroids, thetas):

    """
    Description : Compute a basis of anistropic, shifted and rotated Gaussian
                  Derivatives kernels.

    Params : size      - tuple of int
             order     - int
             sigmas    - Tensor
             centroids - Tensor
             thetas    - Tensor

    Return : A tensor containing transformed Gaussian Derivative kernels of 
             size size[0] x size[1] and of order 0 to 'order'.

    Usage : Used in the function getBases.
    """

    kernels = []
    [x,y] = tensorflow.meshgrid(range(-int(size[0]/2), int(size[0]/2) + 1), range(-int(size[1]/2), int(size[1]/2) + 1))
    x = tensorflow.cast(x, tensorflow.float32)
    y = tensorflow.cast(y, tensorflow.float32)
    counter = 0
    for i in range(order+1):
        for j in range(i+1):

            u = tensorflow.math.add(tensorflow.multiply(tensorflow.math.cos(thetas[counter]), x), tensorflow.math.multiply(tensorflow.math.sin(thetas[counter]), y))
            v = tensorflow.math.add(tensorflow.multiply(-tensorflow.math.sin(thetas[counter]), x), tensorflow.math.multiply(tensorflow.math.cos(thetas[counter]), y))
        
            dGaussx = computeGaussianDerivative(j, tensorflow.math.add(u, - centroids[counter, 0]), sigmas[counter, 0])
            dGaussy = computeGaussianDerivative(i-j, tensorflow.math.add(v, - centroids[counter, 1]), sigmas[counter, 1])
            
            dGauss = tensorflow.math.multiply(dGaussx, dGaussy)
            kernels.append(tensorflow.expand_dims(dGauss, -1))
            counter += 1
    return tensorflow.stack(kernels, axis = -1)

@tensorflow.function
def getBases(size, num_basis, order, sigmas, centroids, thetas):

    """
    Description : Compute all the bases used by the layer by using 
                  the function computeGaussianBasis

    Params : size      - tuple of int
             num_basis - int
             order     - int
             sigmas    - Tensor
             centroids - Tensor
             thetas    - Tensor

    Return : A tensor containing all the bases used by the layer

    Usage : Used in the call function of the FTGDConvLayerRotation class. 
    """

    basis = []
    for i in range(num_basis):
        basis.append(computeGaussianBasis(size, order, sigmas[i,:,:], centroids[i,:,:], thetas[i,:]))
        
    return tensorflow.stack(basis, axis = 0)

def initWeights(input_channels, output_channels, num_basis, order, separated):

    """
    Description : Instanciation of the weights used in the linear combination of the
                  Gaussian Derivative kernels.

    Params : input_channels  - int
             output_channels - int
             num_basis       - int
             order           - int
             separated       - boolean

    Return : A Tensor containing the weights used for the linear combinations.
             If separated = True, two Tensor are returned corresponding to 
             the alphas and betas in [1]

    Usage : Used in the build function of the FTGDConvLayerRotation class.
    """
    
    numFiltersPerBasis = (order + 1)*(order + 2)/2
    
    if separated:

        std_1 = float(np.sqrt(2)/(input_channels+numFiltersPerBasis*num_basis))
        std_2 = float(np.sqrt(2)/(output_channels+numFiltersPerBasis*num_basis))

        weights1 = tensorflow.Variable(initial_value = tensorflow.random.normal(shape = (int(num_basis),  int(input_channels), int(numFiltersPerBasis)), mean=0.0, stddev= std_1, dtype = 'float'), name = 'clWeights1', trainable = True)
        weights2 = tensorflow.Variable(initial_value = tensorflow.random.normal(shape = (int(num_basis),  1,1, int(numFiltersPerBasis), int(output_channels/num_basis)), mean=0, stddev=std_2, dtype = 'float'), name = 'clWeights2', trainable = True)
        
        weights = [weights1, weights2]

    else:
        
        std_1 = float(np.sqrt(2)/(input_channels+output_channels))
        weights = tensorflow.Variable(initial_value = tensorflow.random.normal(shape = (int(num_basis), int(input_channels),   int(output_channels/num_basis), int(numFiltersPerBasis)), mean = 0, stddev= std_1, dtype = 'float'), name = 'clWeights', trainable = True)
        
    return weights

def initGaussianParameters(num_basis, order, random, trainability, sigma_init, mu_init, theta_init):

    """
    Description : Instanciation of the Gaussian parameters, i.e., the scales, 
                  shifts (here called centoids) and orientation (theta).
                  The trainability parameter allows to decide if a Gaussian 
                  parameter should be trainable or not.

    Params : num_basis    - int
             order        - int
             random       - boolean
             trainability - list of boolean
             sigma_init   - float
             mu_init      - float
             theta_init   - float

    Returns : The tensors containing the Gaussian parameters.

    Usage : Used in the build function of the FTGDConvLayerRotation class.
    """

    # 1 kernel for the order 0, 2 kernels for the order 1, 3 kernels for the order 2, etc
    num_kernels_per_basis = (order + 1)*(order + 2)/2

    if random:
        sigmas = tensorflow.Variable(initial_value = tensorflow.random.uniform(shape = (int(num_basis), int(num_kernels_per_basis), 2), minval = 0.5, maxval = 2, dtype = 'float'),  name = 'sigmas', trainable = trainability[0], constraint=tensorflow.keras.constraints.MinMaxNorm(min_value=0.2, max_value=100, rate=1.0, axis=[0, 1, 2]))
        centroids = tensorflow.Variable(initial_value = tensorflow.random.uniform(shape = (int(num_basis), int(num_kernels_per_basis), 2), minval = -1, maxval = 1, dtype = 'float'),  name = 'centroids', trainable = trainability[1])
        thetas = tensorflow.Variable(initial_value = tensorflow.random.uniform(shape = (int(num_basis), int(num_kernels_per_basis)), minval = -math.pi, maxval = math.pi, dtype = 'float'),  name = 'thetas', trainable = trainability[2])
        
    else:
        sigmas = tensorflow.Variable(initial_value = tensorflow.random.uniform(shape = (int(num_basis), int(num_kernels_per_basis), 2), minval = sigma_init, maxval = sigma_init, dtype = 'float'),  name = 'sigmas', trainable = trainability[0], constraint=tensorflow.keras.constraints.MinMaxNorm(min_value=0.2, max_value=100, rate=1.0, axis=[0, 1, 2]))
        centroids = tensorflow.Variable(initial_value = tensorflow.random.uniform(shape = (int(num_basis), int(num_kernels_per_basis), 2), minval = mu_init, maxval = mu_init, dtype = 'float'),  name = 'centroids', trainable = trainability[1])
        thetas = tensorflow.Variable(initial_value = tensorflow.random.uniform(shape = (int(num_basis), int(num_kernels_per_basis)), minval = theta_init, maxval = theta_init, dtype = 'float'),  name = 'thetas', trainable = trainability[2])

    return sigmas, centroids, thetas


@tensorflow.function
def getGaussianFilters(bases, weights, num_basis, input_channels, output_channels, separated):

    """
    Description : Compute the linear combinations given the bases and the weights.

    Params : bases           - Tensor 
             weights         - Tensor
             num_basis       - int
             input_channels  - int
             output_channels - int
             separated       - boolean

    Returns : The tensor containing the filters after linear combination.
              If separated == True, two tensors are returned.

    Usage : Used in the call and deploy functions of the FTGDConvLayerRotation class.
    """

    if separated:

        Filters = []
        for i in range(num_basis):
            considered_basis = bases[i,:,:,:,:]
            considered_basis = tensorflow.tile(considered_basis, [1,1,input_channels,1])

            Gaussfilters = tensorflow.multiply(considered_basis, weights[0][i,:,:])

            Filters.append(Gaussfilters)

        Filters = tensorflow.stack(Filters, axis = 0)

        return Filters

    else:

        Filters = []

        for i in range(num_basis):

            considered_basis = bases[i,:,:,:,:]
            considered_basis = tensorflow.expand_dims(considered_basis, axis = -2)
            considered_basis = tensorflow.tile(considered_basis, [1,1, input_channels, int(output_channels/num_basis), 1])
            Gaussfilters = tensorflow.multiply(considered_basis, weights[i,:,:,:])
            Gaussfilters = tensorflow.reduce_sum(Gaussfilters, axis = -1)
            Filters.append(Gaussfilters)
        Filters = tensorflow.concat(Filters, axis = -1)

        return Filters

@tensorflow.function
def computeOutput(filters, inputs, num_basis, separated, padding_mode, stride = (1,1)):

    """
    Description : Applies the Gaussian filters given by getGaussianFilters to the input
                  the input tensor.

    Params : filters      - List of Tensor (or [List of Tensor, Tensor] if separated=True)
             inputs       - Tensor
             num_basis    - int
             separated    - boolean
             padding_mode - string
             stride       - tuple of int
             
    Returns : The list of output tensor after application of the list Gaussian filters.
              if separated ==  True, the strides are applied during the first
              convolution (the one giving the intermediate tensor fig 1.b. of [1]).

    Usage : Used in the call function of the FTGDConvLayerRotation class.
    """
    if separated:
    
        outputs = []
        for i in range(num_basis):

            res1 = K.conv2d(inputs, filters[0][i,:,:,:,:], strides = stride, padding = padding_mode)
            res2 = K.conv2d(res1, filters[1][i,:,:,:,:], padding = padding_mode)

            outputs.append(res2)

        outputs = tensorflow.concat(outputs, axis = -1)

        return outputs

    else:

        outputs = K.conv2d(inputs, filters, strides=stride, padding = padding_mode)

        return outputs