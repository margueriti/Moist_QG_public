import numpy as np
import matplotlib.pyplot as plt
import integratingfactors as intfact
import rfft2_spectralmethods2D as sp2

class Moist_QG:
    def __init__(self,Nx = 256, Ny = 256, layers =2,length = np.array([2 * np.pi, 2 * np.pi])):
        """Initialize class
          Input Nx,Ny: number of points for spatial discretization i x and y directions
          number of Fourier modes Nk,Nl = Nx, Ny//2 + 1
          layers is 2 for now...
          Default values set to be consistent with the results from Held and Larichev (1995)
          """
        self.param = Model_Parameters(Nx,Ny,layers,length)
        self.var = Model_Variables(self.param)
        self.save = Model_Savedata()
        self.param.initializing = True

    def set_tendency(self):
        if self.param.rain:
            self.tendency = self.precipitation_relaxation
        if not self.param.rain:
            self.tendency = self.nonstiff_pv_tendency_multilayer

    def initial_conditions(self,init_moisture = 0.0 ,noise = 0.01, init_krange=16, init_lrange=16,ic_seed = 1):
        np.random.seed(ic_seed)
        for i in range(self.param.layers):
            self.var.psi_hat[i,:init_krange, :init_lrange] = np.random.normal(loc=0.0, scale=noise, \
                            size=(init_krange,init_lrange)) + 1.j * np.random.normal(loc=0.0, \
                            scale=noise, size=(init_krange,init_lrange))
            self.var.psi_hat[i, -init_krange:, :init_lrange] = np.random.normal(loc=0.0, scale=noise, \
                            size=(init_krange, init_lrange)) + 1.j * np.random.normal(loc=0.0, \
                            scale=noise, size=(init_krange, init_lrange))
            self.var.psi_hat[i,0, 0] = 0.0
        if any(self.param.moisture):
            self.var.water_content_hat = np.zeros((sum(self.param.moisture),self.param.Nl,self.param.Nk),dtype=complex)
            for i in range(len(self.var.water_content_hat)):
                self.var.water_content_hat[i,:init_krange, :init_lrange] = np.random.normal(loc=0.0, scale=noise, \
                            size=(init_krange,init_lrange)) + 1.j * np.random.normal(loc=0.0, \
                            scale=noise, size=(init_krange,init_lrange))
                self.var.water_content_hat[i, -init_krange:, :init_lrange] = np.random.normal(loc=0.0, scale=noise, \
                            size=(init_krange, init_lrange)) + 1.j * np.random.normal(loc=0.0, \
                            scale=noise, size=(init_krange, init_lrange))
                self.var.water_content_hat[i,0, 0] = init_moisture*self.param.Nx*self.param.Ny
                self.var.water_content_hat[i] = self.param.latent_heating*self.var.water_content_hat[i]
        self.potential_vorticity_2L()
        self.var.current_tendency = np.zeros_like(self.var.pv_hat)

    def potential_vorticity_2L(self):
        self.var.pv_hat = np.zeros((self.param.total_layers, self.param.Nl, self.param.Nk), dtype=complex)
        baroclinic = self.var.psi_hat[0]-self.var.psi_hat[1]
        laplace2 = sp2.spectral_Laplacian2(self.var.psi_hat[1],self.param)
        self.var.pv_hat[0] = sp2.spectral_Laplacian2(self.var.psi_hat[0],self.param)-baroclinic*self.param.RWN[0]**2
        self.var.pv_hat[1] = laplace2+baroclinic*self.param.RWN[1]**2
        for i in np.nonzero(self.param.moisture)[0]:
            n = np.sum(self.param.moisture[:i])
            m = self.param.layers+n
            self.var.pv_hat[m] = laplace2+(self.param.RWN[i]**2*baroclinic+self.var.water_content_hat[n])/(1-self.param.latent_heating)

    def initial_savedata(self):
        self.save.pv_hat = np.array([self.var.pv_hat])
        self.save.psi_hat = np.array([self.var.psi_hat])
        if any(self.param.moisture):
            self.save.water_content_hat = np.array([self.var.water_content_hat])
        if self.param.rain:
            self.save.precip = np.array([self.var.precip])

    def update_savedata(self):
        self.save.pv_hat = np.append(self.save.pv_hat,[self.var.pv_hat],axis=0)
        self.save.psi_hat = np.append(self.save.psi_hat,[self.var.psi_hat],axis=0)
        if any(self.param.moisture):
            self.save.water_content_hat = np.append(self.save.water_content_hat,[self.var.water_content_hat],axis=0)
        if self.param.rain:
            self.save.precip = np.append(self.save.precip,[self.var.precip],axis=0)

    def moisture_update(self):
        mean_water_content = self.var.water_content_hat[0,0,0]+(self.param.evaporation-self.var.mean_precip)*self.param.dt
        self.var.water_content_hat[0] = (1-self.param.latent_heating)*(self.var.pv_hat[2]-self.var.pv_hat[1])-self.param.latent_heating*self.param.RWN[1]**2*(self.var.psi_hat[0]-self.var.psi_hat[1]) #not generalized, specific to 2 layers with 1 moist
        self.var.water_content_hat[0,0,0]=mean_water_content

    def velocity_multilayer(self):
        for i in range(0,self.param.layers):
            self.var.u_hat[i] = -sp2.spectral_y_deriv(self.var.psi_hat[i],self.param)
            self.var.v_hat[i] = sp2.spectral_x_deriv(self.var.psi_hat[i],self.param)

    def velocitymag_multilayer(self):
        self.velocity_multilayer()
        renorm = self.param.Nx*self.param.Ny
        self.var.u = sum(np.sqrt(np.abs((self.var.u_hat[:,0,0]/renorm)**2+(self.var.v_hat[:,0,0]/renorm)**2)))

    def nonstiff_pv_tendency_multilayer(self):
        for i in self.param.moist_indices:
            m = self.param.layers+np.sum(self.param.moisture[:i])
            self.var.current_tendency[i],self.var.current_tendency[m] = sp2.double_spectral_Jacobian_antialiasing(self.var.psi_hat[i],self.var.pv_hat[i],self.var.pv_hat[m],self.param)
        for i in self.param.dry_indices:
            self.var.current_tendency[i] = sp2.spectral_Jacobian_antialiasing(self.var.psi_hat[i],self.var.pv_hat[i],self.param)
        self.var.current_tendency = -self.var.current_tendency

    def precipitation_relaxation(self):
        surplus_hat = self.var.water_content_hat[0] - self.param.CC*(self.var.psi_hat[0]-self.var.psi_hat[1])
        surplus_hat[0,0] = surplus_hat[0,0] + self.param.CC * self.var.water_content_hat[0,0,0]
        surplus = np.fft.irfft2(surplus_hat)
        self.var.precip = np.where(surplus>0.0,surplus,surplus*0.0)/self.param.tau
        if self.param.latent_heating==0:
            self.var.precip=0*self.var.precip
        self.var.precip_hat = np.fft.rfft2(self.var.precip)
        self.var.mean_precip = self.var.precip_hat[0,0]
        self.var.precip_hat[0,0]=0.0+0.0j
        self.nonstiff_pv_tendency_multilayer()
        self.var.current_tendency = self.var.current_tendency + np.array([-self.var.precip_hat, self.var.precip_hat, np.zeros_like(self.var.precip_hat)]) #not generalized; specific to 2 layers with 1 moist

class Model_Parameters:
    def __init__(self,Nx=256,Ny=256,layers=2,length = np.array([2 * np.pi, 2 * np.pi])):
        self.layers=layers
        self.Nx = Nx
        self.Ny = Ny
        self.Nl = Ny
        self.Nk = Nx//2 + 1
        self.mid = self.Nl//2
        self.mid2 = self.Nl-self.mid
        self.Nx2 = 3*self.Nx//2
        self.Ny2 = 3*self.Ny//2
        self.Nl2 = self.Ny2
        self.Nk2 = self.Nx2//2 + 1
        self.M=self.Nk2-self.Nk
        self.N=self.Nl2-self.Nl
        self.renorm = (self.Nx2/self.Nx)*(self.Ny2/self.Ny)
        self.length = length
        self.xymin = -length / 2
        self.xymax = length / 2
        self.freqsx = np.fft.fftfreq(Nx)*(2*np.pi/length[0])*Nx
        self.freqsy = np.fft.fftfreq(Ny)*(2*np.pi/length[1])*Ny

    def set_dry_parameters(self,
        damping = np.array([0.0, 0.16]),
        beta = 0.78,
        RWN = np.array([50.0, 50.0]),
        mean_velocity = np.array([0.5, -0.5]),dissipation_coeff=0.008):
        self.mean_velocity = mean_velocity
        self.U = np.abs(mean_velocity[0] - mean_velocity[1])
        self.RWN = RWN
        self.lambdas = np.sqrt(np.sum(self.RWN**2)/len(self.RWN))
        self.damping = damping*self.U*self.RWN[-1]
        self.nu = dissipation_coeff*self.U/(self.lambdas)**7
        self.num = self.nu
        self.beta = beta
        self.criticality = self.U*self.lambdas**2/self.beta

    def set_moist_parameters(self,
        latent_heating = 0.2,
        CC = 2.0,
        moisture = np.array([False, True], dtype=np.bool),
        rain = True,
        evaporation = 1.39):
        self.latent_heating = latent_heating
        self.CC = CC*latent_heating*self.RWN[1]**2
        self.gamma = self.beta - ( self.RWN[1]**2*self.U + self.CC) / (
                    1 - latent_heating)
        self.moisture = moisture
        self.moist_indices = np.nonzero(moisture)[0]
        self.dry_indices = np.where(moisture==False)[0]
        self.total_layers = self.layers + sum(self.moisture)
        self.rain = rain
        self.evaporation = self.latent_heating*evaporation*self.Nx*self.Ny/(self.RWN[1]**2*self.U)
        if sum(self.moisture) == 0:
            self.rain = False

    def set_time_parameters(self,dt = 0.01,Nstep= 100, Nout = 100, tau=0.15):
        self.dt = dt
        self.tau = tau
        self.endtime = Nstep * dt
        self.timesteps = Nstep
        self.output = Nout
        self.time=np.linspace(0.0,self.endtime,Nstep//Nout+1)
        self.LH_coeff = self.dt/(1-self.latent_heating)

class Model_Variables:
    def __init__(self,param):
        self.psi_hat = np.zeros((param.layers, param.Nl, param.Nk), dtype=complex)
        self.u_hat = np.zeros_like(self.psi_hat)
        self.v_hat = np.zeros_like(self.u_hat)
        self.mean_precip=0.0

class Model_Savedata:
    def __init__(self):
        savedata=None

class Timestepping_AB3IF:
    """Timestepping Moist_QG with Adams-Bashforth 3 with an integrating factor.
    """
    def __init__(self,MQG):
        self.MQG = MQG

    def set_integrating_factor(self):
        self.integrating_factor,self.Lin_op, self.q2s = intfact.integratingfactor(self.MQG.param)

    def tendency_update(self):
        for j in self.MQG.param.moist_indices:
            m = self.MQG.param.layers+np.sum(self.MQG.param.moisture[:j])
            self.MQG.var.oldold_tendency[m,:,:] = np.sum(self.integrating_factor[i,m,:,:]*self.MQG.var.old_tendency[i,:,:] for i in range(self.MQG.param.total_layers))
        for j in self.MQG.param.moist_indices:
            m = self.MQG.param.layers+np.sum(self.MQG.param.moisture[:j])
            self.MQG.var.old_tendency[m,:,:] = np.sum(self.integrating_factor[i,m,:,:]*self.MQG.var.current_tendency[i,:,:] for i in range(self.MQG.param.total_layers))
        for j in range(0,self.MQG.param.layers):
            self.MQG.var.oldold_tendency[j,:,:] = np.sum(self.integrating_factor[i,j,:,:]*self.MQG.var.old_tendency[i,:,:] for i in range(self.MQG.param.layers))
        for j in range(0,self.MQG.param.layers):
            self.MQG.var.old_tendency[j,:,:] = np.sum(self.integrating_factor[i,j,:,:]*self.MQG.var.current_tendency[i,:,:] for i in range(self.MQG.param.layers))
        self.MQG.tendency()

    def initial_tendencies(self,method='AB3IF'):
        self.MQG.tendency()
        self.MQG.var.old_tendency = self.MQG.var.current_tendency
        self.MQG.var.oldold_tendency = self.MQG.var.old_tendency
        #self.tendency_update()
        #self.tendency_update()

    def q2s_conversion(self):
        for j in range(0,self.MQG.param.layers):
            self.MQG.var.psi_hat[j,:,:]=np.sum(self.q2s[i,j,:,:]*self.MQG.var.pv_hat[i,:,:] for i in range(self.MQG.param.layers))

    def timestep(self):
        self.MQG.var.pv_hat = self.MQG.var.pv_hat+self.MQG.param.dt*(23.*self.MQG.var.current_tendency-16.*self.MQG.var.old_tendency+5.*self.MQG.var.oldold_tendency)/12.#Adams-Bashforth 3
        pv_hat_new = np.zeros_like(self.MQG.var.pv_hat)
        for j in range(0,self.MQG.param.total_layers):
            pv_hat_new[j,:,:] = np.sum(self.integrating_factor[j,i,:,:]*self.MQG.var.pv_hat[i,:,:] for i in range(self.MQG.param.total_layers))
        self.MQG.var.pv_hat = pv_hat_new
        self.tendency_update()
        self.q2s_conversion()
        self.MQG.var.psi_hat[:,0,0]=self.psiave
        self.MQG.var.pv_hat[0:self.MQG.param.layers,0,0]=self.pvave
        self.MQG.moisture_update()

    def timestepping(self):
        self.set_integrating_factor()
        self.psiave = self.MQG.var.psi_hat[:,0,0]
        self.pvave = self.MQG.var.pv_hat[0:self.MQG.param.layers,0,0]
        if self.MQG.param.initializing:
            self.MQG.set_tendency()
            self.initial_tendencies()
            self.MQG.initial_savedata()
            self.MQG.param.initializing = False
        #self.start_plotting
        self.FT_factor = self.MQG.param.Nx*self.MQG.param.Ny
        self.print_to_terminal(0)
        for n in range(0,self.MQG.param.timesteps):
            self.timestep()
            if (n+1)%self.MQG.param.output==0:
                self.MQG.update_savedata()
                self.print_to_terminal(n+1)
                #self.update_plot()

    def print_to_terminal(self,n):
        for j in self.MQG.param.moist_indices:
            m = self.MQG.param.layers+np.sum(self.MQG.param.moisture[:j])
            print ('P0='+str(self.MQG.var.mean_precip/self.FT_factor)+', m0='+str(self.MQG.var.water_content_hat[0,0,0]/self.FT_factor))
        self.MQG.velocitymag_multilayer()
        print('time='+str((n)*self.MQG.param.dt)+', u='+str(round(np.max(self.MQG.var.u)*100)/100))

    def start_plotting(self):
        plt.ion()
        fig, axs = plt.subplots(nrows=2, ncols=2)
        Title = 'time='
        BT = self.MQG.var.pv_hat[0]+self.MQG.var.pv_hat[1]
        BC = self.MQG.var.pv_hat[0]-self.MQG.var.pv_hat[1]
        ln1 = axs[0][0].imshow(np.log(np.abs(BT[-self.MQG.param.Nl:,:])+1e-20),extent=[0.0,self.MQG.param.freqsx.max(),self.MQG.param.freqsy.max(),0.0])
        ln2 = axs[1][0].imshow(np.log(np.abs(BC[-self.MQG.param.Nl:,:])+1e-20),extent=[0.0,self.MQG.param.freqsx.max(),self.MQG.param.freqsy.max(),0.0])
        ln3 = axs[0][1].imshow(np.fft.irfft2(BT),extent=[self.MQG.param.xymin[0],self.MQG.param.xymax[0],self.MQG.param.xymin[1],self.MQG.param.xymax[1]])
        ln4 = axs[1][1].imshow(np.fft.irfft2(BC),extent=[self.MQG.param.xymin[0],self.MQG.param.xymax[0],self.MQG.param.xymin[1],self.MQG.param.xymax[1]])
        axs[0][0].set_title('BTPV spectrum')
        axs[1][0].set_title('BCPV spectrum')
        axs[0][1].set_title('BTPV')
        axs[1][1].set_title('BCPV')
        cb1=fig.colorbar(ln1, ax=axs[0][0])
        cb2=fig.colorbar(ln2, ax=axs[1][0])
        cb3=fig.colorbar(ln3, ax=axs[0][1])
        cb4=fig.colorbar(ln4, ax=axs[1][1])
        tx = fig.suptitle(Title+str(0.0))
        plt.pause(0.000001)
        plt.draw()

    def update_plot(self):
        BT = self.MQG.var.pv_hat[0]+self.MQG.var.pv_hat[1]
        BC = self.MQG.var.pv_hat[0]-self.MQG.var.pv_hat[1]
        self.update_spectrum(np.log(np.abs(BT[:self.MQG.param.Nl,:])),ln1)
        self.update_spectrum(np.log(np.abs(BC[:self.MQG.param.Nl,:])+1e-20),ln2)
        self.update_contour(np.fft.irfft2(BT),ln3)
        self.update_contour(np.fft.irfft2(BC),ln4)
        tx.set_text(Title+str(round(n*self.MQG.param.dt*10)/10))
        plt.pause(0.000001)
        plt.draw()

    def update_spectrum(self,new_data,figure):
        vmax = np.max(new_data)
        figure.set_data(new_data)
        figure.set_clim(-12.0,vmax)

    def update_contour(self,new_data,figure):
        vmax = np.max(new_data)
        vmin = np.min(new_data)
        figure.set_data(new_data)
        figure.set_clim(vmin,vmax)

