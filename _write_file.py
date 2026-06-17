import sys; path=sys.argv[1]; data=open(sys.argv[2],'rb').read().decode('utf-8'); open(path,'w',encoding='utf-8').write(data); print('ok') 
